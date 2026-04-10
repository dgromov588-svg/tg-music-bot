import asyncio
import json
import math
import os
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import isodate
from dotenv import load_dotenv

load_dotenv()

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
YT = os.getenv("YOUTUBE_API_KEY", "").strip()
PUB = os.getenv("PUBLISH_CHAT_ID", "").strip()
REG = os.getenv("YOUTUBE_REGION_CODE", "UA").strip() or "UA"
LANG = os.getenv("YOUTUBE_RELEVANCE_LANGUAGE", "uk").strip() or "uk"
MAXR = int(os.getenv("SEARCH_MAX_RESULTS", "10"))
TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
DB = os.getenv("DATABASE_PATH", "data/music_bot.db").strip() or "data/music_bot.db"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
WEBHOOK_SECRET_PATH = os.getenv("WEBHOOK_SECRET_PATH", "").strip() or secrets.token_urlsafe(24)
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
DROP_PENDING_UPDATES = os.getenv("DROP_PENDING_UPDATES", "true").strip().lower() in {"1", "true", "yes", "on"}

if not BOT or not YT or not PUB:
    raise RuntimeError("Fill TELEGRAM_BOT_TOKEN, YOUTUBE_API_KEY, PUBLISH_CHAT_ID")

API = f"https://api.telegram.org/bot{BOT}"
Path(DB).parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute(
    "CREATE TABLE IF NOT EXISTS pub("
    "id INTEGER PRIMARY KEY, "
    "video_id TEXT, "
    "title TEXT, "
    "channel TEXT, "
    "url TEXT, "
    "query TEXT, "
    "label TEXT, "
    "msg_id INTEGER, "
    "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
)
conn.execute("CREATE INDEX IF NOT EXISTS ix_pub_video ON pub(video_id)")
conn.commit()

http = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
cache = {}

HELP = (
    "/orig query — найти оригинал\n"
    "/remix query — найти ремиксы\n"
    "/find query — показать лучший результат и кнопки\n"
    "/add query — сразу опубликовать оригинал в канал\n"
    "/history [N] — последние публикации\n"
    "/republish <video_id> — повторная публикация\n"
    "/help — помощь"
)

NEG = "remix live cover karaoke slowed reverb nightcore sped up lyrics 8d instrumental bass boosted".split()
RPOS = "remix edit mix mashup bootleg vip".split()
RNEG = "live cover karaoke lyrics".split()
OFF = ["official", "official audio", "topic", "vevo"]


def q1(sql, args=()):
    return conn.execute(sql, args).fetchone()


def qall(sql, args=()):
    return conn.execute(sql, args).fetchall()


def add_pub(v, t, c, u, q, l, m):
    conn.execute(
        "INSERT INTO pub(video_id,title,channel,url,query,label,msg_id) VALUES(?,?,?,?,?,?,?)",
        (v, t, c, u, q, l, m),
    )
    conn.commit()


def norm(s):
    return " ".join((s or "").lower().replace("—", " ").replace("-", " ").split())


def dur(v):
    try:
        return int(isodate.parse_duration(v).total_seconds()) if v else None
    except Exception:
        return None


def score(title, channel, desc, secs, views, query, remix=False):
    hay = norm(f"{title} {channel} {desc}")
    title_norm = norm(title)
    q_norm = norm(query)
    sc = 0.0
    tokens = [x for x in q_norm.split() if len(x) > 1]
    sc += sum(18 for x in tokens if x in title_norm)
    if q_norm and q_norm in title_norm:
        sc += 35
    if any(x in hay for x in OFF):
        sc += 22
    if secs is not None:
        if 110 <= secs <= 420:
            sc += 16
        elif secs < 60 or secs > 900:
            sc -= 25
    if views:
        try:
            sc += min(12, math.log10(max(int(views), 1)) * 2)
        except Exception:
            pass
    if remix:
        sc += sum(20 for x in RPOS if x in hay)
        sc -= sum(18 for x in RNEG if x in hay)
    else:
        sc -= sum(30 for x in NEG if x in hay)
        if "official audio" in hay or "audio" in title_norm:
            sc += 10
    return sc


async def tg(method, payload):
    response = await http.post(f"{API}/{method}", json=payload)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data.get("result")


async def yt_search(query, remix=False):
    search_query = (
        f"{query} remix OR edit OR mix"
        if remix
        else f"{query} -remix -live -cover -karaoke -slowed -reverb -nightcore"
    )
    response = await http.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "q": search_query,
            "type": "video",
            "videoCategoryId": "10",
            "maxResults": str(MAXR),
            "regionCode": REG,
            "relevanceLanguage": LANG,
            "safeSearch": "none",
            "key": YT,
        },
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    ids = [x.get("id", {}).get("videoId") for x in items if x.get("id", {}).get("videoId")]

    info = {}
    if ids:
        response = await http.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "contentDetails,statistics",
                "id": ",".join(ids),
                "key": YT,
            },
        )
        response.raise_for_status()
        info = {x.get("id"): x for x in response.json().get("items", []) if x.get("id")}

    out = []
    for item in items:
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        details = info.get(video_id, {})
        secs = dur(details.get("contentDetails", {}).get("duration"))
        views = details.get("statistics", {}).get("viewCount")
        out.append(
            {
                "video_id": video_id,
                "title": snippet.get("title", "Untitled"),
                "channel": snippet.get("channelTitle", "Unknown"),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "secs": secs,
                "views": int(views) if str(views).isdigit() else None,
                "score": score(
                    snippet.get("title", ""),
                    snippet.get("channelTitle", ""),
                    snippet.get("description", ""),
                    secs,
                    views,
                    query,
                    remix,
                ),
            }
        )
    return sorted(out, key=lambda x: x["score"], reverse=True)


async def bundle(query):
    cache_id = secrets.token_urlsafe(6)
    data = {
        "id": cache_id,
        "query": query,
        "orig": await yt_search(query, False),
        "remix": await yt_search(query, True),
    }
    cache[cache_id] = (time.time() + TTL, data)
    return data


def from_cache(cache_id):
    item = cache.get(cache_id)
    if not item or time.time() > item[0]:
        cache.pop(cache_id, None)
        return None
    return item[1]


def fmt_track(track, head, query):
    parts = [head, "", track["title"], f"Канал: {track['channel']}"]
    if track["secs"] is not None:
        parts.append(f"Длительность: {track['secs']//60}:{track['secs']%60:02d}")
    if track["views"] is not None:
        parts.append(f"Просмотры: {track['views']:,}".replace(",", " "))
    parts += [f"Score: {track['score']:.1f}", f"Запрос: {query}", track["url"]]
    return "\n".join(parts)


def kb(rows):
    return {"inline_keyboard": rows}


def dup_msg(row):
    return (
        "Этот ролик уже публиковался.\n\n"
        f"{row['title']}\n"
        f"Канал: {row['channel']}\n"
        f"Тип: {row['label']}\n"
        f"video_id: {row['video_id']}\n"
        f"Повтор: /republish {row['video_id']}\n"
        f"{row['url']}"
    )


async def publish(track, query, label, allow=False):
    old = q1("SELECT * FROM pub WHERE video_id=? ORDER BY id DESC LIMIT 1", (track["video_id"],))
    if old and not allow:
        return {"status": "dup", "row": old}
    post = await tg(
        "sendMessage",
        {
            "chat_id": PUB,
            "text": (
                "🎵 Найден трек\n\n"
                f"{track['title']}\n"
                f"YouTube-канал: {track['channel']}\n"
                f"Тип: {label}\n"
                f"Запрос: {query}\n"
                f"{track['url']}"
            ),
            "reply_markup": kb([[{"text": "Открыть в YouTube", "url": track["url"]}]]),
            "disable_web_page_preview": True,
        },
    )
    add_pub(track["video_id"], track["title"], track["channel"], track["url"], query, label, post.get("message_id"))
    return {"status": "ok", "post": post}


async def on_msg(message):
    text = (message.get("text") or "").strip()
    chat = message["chat"]["id"]
    if not text:
        return
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@", 1)[0].lower()
    arg = arg.strip()

    if cmd in ["/start", "/help"]:
        return await tg("sendMessage", {"chat_id": chat, "text": HELP})

    if cmd == "/history":
        try:
            n = max(1, min(50, int(arg or "10")))
        except Exception:
            return await tg("sendMessage", {"chat_id": chat, "text": "Пример: /history 10"})
        rows = qall("SELECT * FROM pub ORDER BY id DESC LIMIT ?", (n,))
        if not rows:
            return await tg("sendMessage", {"chat_id": chat, "text": "История публикаций пока пустая."})
        lines = [f"Последние публикации: {len(rows)}", ""]
        for i, row in enumerate(rows, 1):
            lines += [
                f"{i}. {row['title']}",
                f"   Тип: {row['label']} | video_id: {row['video_id']}",
                f"   Канал: {row['channel']}",
                f"   Дата: {row['created_at']}",
                "",
            ]
        return await tg("sendMessage", {"chat_id": chat, "text": "\n".join(lines).strip(), "disable_web_page_preview": True})

    if cmd == "/republish":
        if not arg:
            return await tg("sendMessage", {"chat_id": chat, "text": "Пример: /republish dQw4w9WgXcQ"})
        row = q1("SELECT * FROM pub WHERE video_id=? ORDER BY id DESC LIMIT 1", (arg,))
        if not row:
            return await tg("sendMessage", {"chat_id": chat, "text": "Такого video_id нет в истории."})
        track = {"video_id": row["video_id"], "title": row["title"], "channel": row["channel"], "url": row["url"]}
        await publish(track, row["query"], str(row["label"]) + "_REPUBLISH", True)
        return await tg("sendMessage", {"chat_id": chat, "text": f"Переопубликовал:\n{row['title']}\n{row['url']}"})

    if cmd not in ["/orig", "/remix", "/find", "/add"] or not arg:
        return await tg("sendMessage", {"chat_id": chat, "text": "Используй /help"})

    data = await bundle(arg)

    if cmd == "/remix":
        if not data["remix"]:
            return await tg("sendMessage", {"chat_id": chat, "text": "Ремиксы не нашёл."})
        lines = [f"Ремиксы по запросу: {arg}", ""]
        for i, track in enumerate(data["remix"][:3], 1):
            lines += [
                f"{i}. {track['title']}",
                f"   Канал: {track['channel']}",
                f"   Score: {track['score']:.1f}",
                f"   {track['url']}",
                "",
            ]
        rows = [[{"text": "Открыть 1", "url": data["remix"][0]["url"]}]]
        rows += [
            [{"text": f"Опубликовать remix {i+1}", "callback_data": f"pubr|{data['id']}|{i}"}]
            for i, _ in enumerate(data["remix"][:3])
        ]
        return await tg(
            "sendMessage",
            {"chat_id": chat, "text": "\n".join(lines).strip(), "reply_markup": kb(rows), "disable_web_page_preview": True},
        )

    if not data["orig"]:
        return await tg("sendMessage", {"chat_id": chat, "text": "Ничего не нашёл по этому запросу."})

    best = data["orig"][0]
    if cmd == "/add":
        result = await publish(best, arg, "ORIGINAL", False)
        if result["status"] == "dup":
            return await tg(
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": dup_msg(result["row"]),
                    "reply_markup": kb([[{"text": "Открыть", "url": result["row"]["url"]}]]),
                    "disable_web_page_preview": True,
                },
            )
        return await tg(
            "sendMessage",
            {
                "chat_id": chat,
                "text": (
                    "Опубликовал в канал.\n\n"
                    f"{best['title']}\n"
                    f"Канал: {best['channel']}\n"
                    f"video_id: {best['video_id']}\n"
                    f"message_id: {result['post'].get('message_id')}\n"
                    f"{best['url']}"
                ),
                "reply_markup": kb([[{"text": "Открыть в YouTube", "url": best["url"]}]]),
                "disable_web_page_preview": True,
            },
        )

    return await tg(
        "sendMessage",
        {
            "chat_id": chat,
            "text": fmt_track(best, "Лучший оригинал", arg),
            "reply_markup": kb(
                [
                    [{"text": "Открыть", "url": best["url"]}],
                    [{"text": "Показать ремиксы", "callback_data": f"showr|{data['id']}"}],
                    [{"text": "Опубликовать оригинал", "callback_data": f"pubo|{data['id']}"}],
                ]
            ),
            "disable_web_page_preview": True,
        },
    )


async def on_cb(callback):
    callback_id = callback["id"]
    data = callback.get("data", "")
    message = callback.get("message") or {}
    chat = message.get("chat", {}).get("id")
    parts = data.split("|")
    if len(parts) < 2:
        return await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Некорректная кнопка", "show_alert": True})

    action, bundle_id = parts[0], parts[1]
    bundle_data = from_cache(bundle_id)
    if not bundle_data:
        return await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Кэш истёк, повтори поиск", "show_alert": True})

    try:
        if action == "showr":
            await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Показываю ремиксы"})
            return await on_msg({"chat": {"id": chat}, "text": "/remix " + bundle_data["query"]})

        if action == "pubo":
            result = await publish(bundle_data["orig"][0], bundle_data["query"], "ORIGINAL", False)
            if result["status"] == "dup":
                await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Уже был опубликован", "show_alert": True})
                return await tg(
                    "sendMessage",
                    {
                        "chat_id": chat,
                        "text": dup_msg(result["row"]),
                        "reply_markup": kb([[{"text": "Открыть", "url": result["row"]["url"]}]]),
                        "disable_web_page_preview": True,
                    },
                )
            return await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Оригинал опубликован"})

        if action == "pubr":
            index = int(parts[2]) if len(parts) > 2 else 0
            if index >= len(bundle_data["remix"]):
                return await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Ремикс не найден", "show_alert": True})
            result = await publish(bundle_data["remix"][index], bundle_data["query"], "REMIX", False)
            if result["status"] == "dup":
                await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Уже был опубликован", "show_alert": True})
                return await tg(
                    "sendMessage",
                    {
                        "chat_id": chat,
                        "text": dup_msg(result["row"]),
                        "reply_markup": kb([[{"text": "Открыть", "url": result["row"]["url"]}]]),
                        "disable_web_page_preview": True,
                    },
                )
            return await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Ремикс опубликован"})
    except Exception:
        return await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Ошибка. Проверь права бота и лог", "show_alert": True})


async def process_update(update):
    if "message" in update:
        return await on_msg(update["message"])
    if "callback_query" in update:
        return await on_cb(update["callback_query"])
    return None


async def setup_bot():
    await tg(
        "setMyCommands",
        {
            "commands": [
                {"command": "orig", "description": "Найти оригинал трека"},
                {"command": "remix", "description": "Найти ремиксы"},
                {"command": "find", "description": "Найти трек и показать кнопки"},
                {"command": "add", "description": "Опубликовать оригинал в канал"},
                {"command": "history", "description": "Показать историю публикаций"},
                {"command": "republish", "description": "Переопубликовать по video_id"},
                {"command": "help", "description": "Показать помощь"},
            ]
        },
    )


async def configure_webhook():
    await setup_bot()
    await tg("deleteWebhook", {"drop_pending_updates": DROP_PENDING_UPDATES})
    if not WEBHOOK_BASE_URL:
        print("WEBHOOK_BASE_URL не указан. Сервер стартует без регистрации webhook.")
        print(f"Укажи WEBHOOK_BASE_URL и затем вызови /set-webhook?url=https://your-domain/{WEBHOOK_SECRET_PATH}")
        return
    payload = {
        "url": f"{WEBHOOK_BASE_URL}/{WEBHOOK_SECRET_PATH}",
        "drop_pending_updates": DROP_PENDING_UPDATES,
        "allowed_updates": ["message", "callback_query"],
    }
    if WEBHOOK_SECRET_TOKEN:
        payload["secret_token"] = WEBHOOK_SECRET_TOKEN
    result = await tg("setWebhook", payload)
    print("Webhook установлен:", result)


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "TgMusicBotWebhook/1.0"

    def _send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            return self._send_json(200, {"ok": True, "service": "tg-music-bot-webhook"})
        if parsed.path == "/set-webhook":
            params = parse_qs(parsed.query)
            override_url = (params.get("url", [""])[0] or WEBHOOK_BASE_URL).rstrip("/")
            if not override_url:
                return self._send_json(400, {"ok": False, "error": "missing url"})
            try:
                asyncio.run(
                    tg(
                        "setWebhook",
                        {
                            "url": f"{override_url}/{WEBHOOK_SECRET_PATH}",
                            "drop_pending_updates": DROP_PENDING_UPDATES,
                            "allowed_updates": ["message", "callback_query"],
                            **({"secret_token": WEBHOOK_SECRET_TOKEN} if WEBHOOK_SECRET_TOKEN else {}),
                        },
                    )
                )
                return self._send_json(200, {"ok": True, "webhook_path": f"/{WEBHOOK_SECRET_PATH}"})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})
        if parsed.path == "/delete-webhook":
            try:
                asyncio.run(tg("deleteWebhook", {"drop_pending_updates": DROP_PENDING_UPDATES}))
                return self._send_json(200, {"ok": True, "deleted": True})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "error": str(exc)})
        return self._send_text(404, "not found")

    def do_POST(self):
        expected_path = f"/{WEBHOOK_SECRET_PATH}"
        if self.path != expected_path:
            return self._send_text(404, "not found")

        if WEBHOOK_SECRET_TOKEN:
            got = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if got != WEBHOOK_SECRET_TOKEN:
                return self._send_text(403, "forbidden")

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            update = json.loads(raw.decode("utf-8"))
            asyncio.run(process_update(update))
            return self._send_json(200, {"ok": True})
        except Exception as exc:
            return self._send_json(500, {"ok": False, "error": str(exc)})


def main():
    asyncio.run(configure_webhook())
    server = ThreadingHTTPServer((WEBHOOK_HOST, WEBHOOK_PORT), WebhookHandler)
    print(f"Webhook server listening on http://{WEBHOOK_HOST}:{WEBHOOK_PORT}")
    print(f"Webhook path: /{WEBHOOK_SECRET_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        asyncio.run(http.aclose())
        conn.close()


if __name__ == "__main__":
    main()
