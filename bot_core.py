import math
import os
import secrets
import sqlite3
import time
from pathlib import Path

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
ADMIN_USER_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_USER_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

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
user_state = {}

NEG = "remix live cover karaoke slowed reverb nightcore sped up lyrics 8d instrumental bass boosted".split()
RPOS = "remix edit mix mashup bootleg vip".split()
RNEG = "live cover karaoke lyrics".split()
OFF = ["official", "official audio", "topic", "vevo"]

BTN_FIND = "🎧 Найти оригинал"
BTN_REMIX = "🔥 Найти ремиксы"
BTN_PUBLISH = "📢 Опубликовать в канал"
BTN_HISTORY = "🕘 История"
BTN_ADMIN = "⚙️ Админ-панель"
BTN_HELP = "ℹ️ Помощь"
BTN_MENU = "🏠 Меню"
BTN_CANCEL = "❌ Отмена"

HELP_TEXT = (
    "🎵 Музыкальный бот\n\n"
    "Что умеет:\n"
    "• ищет оригинальные версии треков\n"
    "• показывает ремиксы\n"
    "• публикует найденный трек в канал\n"
    "• показывает историю публикаций\n"
    "• даёт быстрые админ-инструменты\n\n"
    "Команды:\n"
    "/start — открыть красивое меню\n"
    "/menu — открыть меню\n"
    "/orig <запрос> — найти оригинал\n"
    "/remix <запрос> — найти ремиксы\n"
    "/find <запрос> — найти и показать карточку\n"
    "/add <запрос> — сразу опубликовать оригинал\n"
    "/history [N] — последние публикации\n"
    "/republish <video_id> — повторная публикация\n"
    "/admin — админ-панель\n"
    "/help — помощь"
)

WELCOME_TEXT = (
    "✨ Добро пожаловать в музыкальный бот\n\n"
    "Выбери действие кнопками ниже или просто отправь название трека.\n"
    "Пример: Linkin Park Numb"
)


def main_menu_keyboard():
    return {
        "keyboard": [
            [{"text": BTN_FIND}, {"text": BTN_REMIX}],
            [{"text": BTN_PUBLISH}, {"text": BTN_HISTORY}],
            [{"text": BTN_ADMIN}, {"text": BTN_HELP}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Напиши артиста и название трека…",
    }


def cancel_keyboard():
    return {
        "keyboard": [[{"text": BTN_CANCEL}], [{"text": BTN_MENU}]],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Напиши запрос или нажми Отмена…",
    }


def inline(rows):
    return {"inline_keyboard": rows}


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


def dur(value):
    try:
        return int(isodate.parse_duration(value).total_seconds()) if value else None
    except Exception:
        return None


def fmt_duration(seconds):
    if seconds is None:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


def thumbnail_url(video_id):
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


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


def set_state(chat_id, mode):
    user_state[chat_id] = mode


def clear_state(chat_id):
    user_state.pop(chat_id, None)


def get_state(chat_id):
    return user_state.get(chat_id)


def is_admin(chat_id):
    return not ADMIN_USER_IDS or chat_id in ADMIN_USER_IDS


async def tg(method, payload):
    response = await http.post(f"{API}/{method}", json=payload)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data.get("result")


async def send_text(chat_id, text, reply_markup=None, disable_preview=True):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_preview,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return await tg("sendMessage", payload)


async def send_photo(chat_id, photo, caption, reply_markup=None):
    payload = {"chat_id": chat_id, "photo": photo, "caption": caption}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return await tg("sendPhoto", payload)


async def send_track_preview(chat_id, track, caption, reply_markup=None):
    try:
        return await send_photo(chat_id, thumbnail_url(track["video_id"]), caption, reply_markup)
    except Exception:
        return await send_text(chat_id, caption, reply_markup=reply_markup)


async def answer_callback(callback_id, text, alert=False):
    return await tg(
        "answerCallbackQuery",
        {"callback_query_id": callback_id, "text": text, "show_alert": alert},
    )


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
            params={"part": "contentDetails,statistics", "id": ",".join(ids), "key": YT},
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


def track_card(track, query, title="🎧 Лучшее совпадение"):
    lines = [
        title,
        "",
        f"🎵 {track['title']}",
        f"📺 Канал: {track['channel']}",
        f"⏱ Длительность: {fmt_duration(track['secs'])}",
    ]
    if track["views"] is not None:
        lines.append(f"👀 Просмотры: {track['views']:,}".replace(",", " "))
    lines += [
        f"🎯 Оценка: {track['score']:.1f}",
        f"🔎 Запрос: {query}",
        "",
        track["url"],
    ]
    return "\n".join(lines)


def remix_list_card(items, query):
    lines = [f"🔥 Ремиксы по запросу: {query}", ""]
    for i, track in enumerate(items[:3], 1):
        lines += [
            f"{i}. {track['title']}",
            f"   📺 {track['channel']}",
            f"   ⏱ {fmt_duration(track['secs'])}   🎯 {track['score']:.1f}",
            f"   {track['url']}",
            "",
        ]
    return "\n".join(lines).strip()


def history_card(rows):
    lines = [f"🕘 Последние публикации: {len(rows)}", ""]
    for i, row in enumerate(rows, 1):
        lines += [
            f"{i}. {row['title']}",
            f"   🏷 {row['label']}  •  🆔 {row['video_id']}",
            f"   📺 {row['channel']}",
            f"   🗓 {row['created_at']}",
            "",
        ]
    return "\n".join(lines).strip()


def duplicate_card(row):
    return (
        "⚠️ Этот ролик уже публиковался\n\n"
        f"🎵 {row['title']}\n"
        f"📺 Канал: {row['channel']}\n"
        f"🏷 Тип: {row['label']}\n"
        f"🆔 video_id: {row['video_id']}\n"
        f"🔁 Повтор: /republish {row['video_id']}\n\n"
        f"{row['url']}"
    )


def admin_card(total_posts, unique_videos):
    scope = "все пользователи" if not ADMIN_USER_IDS else ", ".join(str(x) for x in sorted(ADMIN_USER_IDS))
    return (
        "⚙️ Админ-панель\n\n"
        f"📢 Канал публикации: {PUB}\n"
        f"🗃 База: {DB}\n"
        f"🧾 Всего публикаций: {total_posts}\n"
        f"🎬 Уникальных видео: {unique_videos}\n"
        f"👤 Доступ: {scope}"
    )


def selector_buttons(bundle_data, selected_idx=0):
    rows = []
    for i, track in enumerate(bundle_data["orig"][:3]):
        icons = ["1️⃣", "2️⃣", "3️⃣"]
        prefix = "✅" if i == selected_idx else icons[i]
        rows.append({
            "text": f"{prefix} {track['title'][:18]}",
            "callback_data": f"sel|{bundle_data['id']}|{i}",
        })
    return rows


def main_inline(bundle_data, selected_idx=0):
    current = bundle_data["orig"][selected_idx]
    return inline(
        [
            [
                {"text": "▶️ Открыть", "url": current["url"]},
                {"text": "📢 В канал", "callback_data": f"pubo|{bundle_data['id']}|{selected_idx}"},
            ],
            selector_buttons(bundle_data, selected_idx),
            [
                {"text": "🔥 Ремиксы", "callback_data": f"showr|{bundle_data['id']}"},
                {"text": "🏠 Меню", "callback_data": "menu"},
            ],
        ]
    )


def remixes_inline(bundle_data):
    rows = []
    for i, track in enumerate(bundle_data["remix"][:3]):
        rows.append(
            [
                {"text": f"▶️ Remix {i+1}", "url": track["url"]},
                {"text": f"📢 Remix {i+1}", "callback_data": f"pubr|{bundle_data['id']}|{i}"},
            ]
        )
    rows.append([{"text": "🏠 Меню", "callback_data": "menu"}])
    return inline(rows)


def admin_inline():
    return inline(
        [
            [
                {"text": "📡 Статус канала", "callback_data": "admin|status"},
                {"text": "🕘 Последние 5", "callback_data": "admin|recent"},
            ],
            [
                {"text": "🧪 Тест-пост", "callback_data": "admin|test"},
                {"text": "🏠 Меню", "callback_data": "menu"},
            ],
        ]
    )


async def show_menu(chat_id, text=None):
    clear_state(chat_id)
    return await send_text(chat_id, text or WELCOME_TEXT, reply_markup=main_menu_keyboard())


async def ask_for_query(chat_id, mode):
    clear_state(chat_id)
    set_state(chat_id, mode)
    titles = {
        "orig": "🎧 Пришли название трека или артист + трек.",
        "remix": "🔥 Пришли трек, для которого нужно найти ремиксы.",
        "publish": "📢 Пришли трек, который нужно найти и сразу опубликовать в канал.",
    }
    return await send_text(chat_id, titles[mode], reply_markup=cancel_keyboard())


async def handle_original(chat_id, query):
    data = await bundle(query)
    if not data["orig"]:
        return await send_text(chat_id, "😕 Ничего не нашёл. Попробуй уточнить запрос.", reply_markup=main_menu_keyboard())
    return await send_track_preview(
        chat_id,
        data["orig"][0],
        track_card(data["orig"][0], query, "✨ Лучший оригинал"),
        reply_markup=main_inline(data, 0),
    )


async def handle_remix(chat_id, query):
    data = await bundle(query)
    if not data["remix"]:
        return await send_text(chat_id, "😕 Ремиксы не нашёл. Попробуй другой запрос.", reply_markup=main_menu_keyboard())
    return await send_text(chat_id, remix_list_card(data["remix"], query), reply_markup=remixes_inline(data))


async def handle_publish(chat_id, query):
    data = await bundle(query)
    if not data["orig"]:
        return await send_text(chat_id, "😕 Ничего не нашёл для публикации.", reply_markup=main_menu_keyboard())
    best = data["orig"][0]
    result = await publish(best, query, "ORIGINAL", False)
    if result["status"] == "dup":
        return await send_text(
            chat_id,
            duplicate_card(result["row"]),
            reply_markup=inline(
                [
                    [{"text": "▶️ Открыть", "url": result["row"]["url"]}],
                    [{"text": "🏠 Меню", "callback_data": "menu"}],
                ]
            ),
        )
    return await send_track_preview(
        chat_id,
        best,
        (
            "✅ Трек опубликован\n\n"
            f"🎵 {best['title']}\n"
            f"📺 {best['channel']}\n"
            f"🆔 {best['video_id']}\n"
            f"✉️ message_id: {result['post'].get('message_id')}\n\n"
            f"{best['url']}"
        ),
        reply_markup=inline(
            [
                [{"text": "▶️ Открыть", "url": best["url"]}],
                [{"text": "🏠 Меню", "callback_data": "menu"}],
            ]
        ),
    )


async def handle_history(chat_id, arg="10"):
    try:
        n = max(1, min(50, int(arg or "10")))
    except Exception:
        return await send_text(chat_id, "Пример: /history 10", reply_markup=main_menu_keyboard())
    rows = qall("SELECT * FROM pub ORDER BY id DESC LIMIT ?", (n,))
    if not rows:
        return await send_text(chat_id, "🕘 История публикаций пока пустая.", reply_markup=main_menu_keyboard())
    return await send_text(chat_id, history_card(rows), reply_markup=main_menu_keyboard())


async def handle_republish(chat_id, video_id):
    if not video_id:
        return await send_text(chat_id, "Пример: /republish dQw4w9WgXcQ", reply_markup=main_menu_keyboard())
    row = q1("SELECT * FROM pub WHERE video_id=? ORDER BY id DESC LIMIT 1", (video_id,))
    if not row:
        return await send_text(chat_id, "Такого video_id нет в истории.", reply_markup=main_menu_keyboard())
    track = {
        "video_id": row["video_id"],
        "title": row["title"],
        "channel": row["channel"],
        "url": row["url"],
    }
    await publish(track, row["query"], str(row["label"]) + "_REPUBLISH", True)
    return await send_text(
        chat_id,
        f"🔁 Переопубликовал:\n\n🎵 {row['title']}\n{row['url']}",
        reply_markup=main_menu_keyboard(),
    )


async def publish(track, query, label, allow=False):
    old = q1("SELECT * FROM pub WHERE video_id=? ORDER BY id DESC LIMIT 1", (track["video_id"],))
    if old and not allow:
        return {"status": "dup", "row": old}
    caption = (
        "📢 Публикация в канал\n\n"
        f"🎵 {track['title']}\n"
        f"📺 YouTube-канал: {track['channel']}\n"
        f"🏷 Тип: {label}\n"
        f"🔎 Запрос: {query}\n\n"
        f"{track['url']}"
    )
    try:
        post = await send_photo(
            PUB,
            thumbnail_url(track["video_id"]),
            caption,
            reply_markup=inline([[{"text": "▶️ Открыть в YouTube", "url": track["url"]}]]),
        )
    except Exception:
        post = await send_text(
            PUB,
            caption,
            reply_markup=inline([[{"text": "▶️ Открыть в YouTube", "url": track["url"]}]]),
        )
    add_pub(track["video_id"], track["title"], track["channel"], track["url"], query, label, post.get("message_id"))
    return {"status": "ok", "post": post}


async def show_admin_panel(chat_id):
    if not is_admin(chat_id):
        return await send_text(chat_id, "⛔️ Нет доступа к админ-панели.", reply_markup=main_menu_keyboard())
    total_posts = q1("SELECT COUNT(*) AS c FROM pub")["c"]
    unique_videos = q1("SELECT COUNT(DISTINCT video_id) AS c FROM pub")["c"]
    return await send_text(chat_id, admin_card(total_posts, unique_videos), reply_markup=admin_inline())


async def handle_admin_action(chat_id, action):
    if not is_admin(chat_id):
        return await send_text(chat_id, "⛔️ Нет доступа к админ-панели.", reply_markup=main_menu_keyboard())
    if action == "status":
        try:
            chat = await tg("getChat", {"chat_id": PUB})
            username = f"@{chat.get('username')}" if chat.get("username") else "—"
            text = (
                "📡 Статус канала\n\n"
                f"Название: {chat.get('title', '—')}\n"
                f"Тип: {chat.get('type', '—')}\n"
                f"Username: {username}"
            )
            return await send_text(chat_id, text, reply_markup=admin_inline())
        except Exception as exc:
            return await send_text(chat_id, f"Не смог получить статус канала:\n{exc}", reply_markup=admin_inline())
    if action == "recent":
        rows = qall("SELECT * FROM pub ORDER BY id DESC LIMIT 5")
        if not rows:
            return await send_text(chat_id, "Публикаций пока нет.", reply_markup=admin_inline())
        return await send_text(chat_id, history_card(rows), reply_markup=admin_inline())
    if action == "test":
        payload = (
            "🧪 Тестовый пост из админ-панели\n\n"
            f"Канал: {PUB}\n"
            f"Время: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            await send_text(PUB, payload)
            return await send_text(chat_id, "✅ Тестовый пост отправлен в канал.", reply_markup=admin_inline())
        except Exception as exc:
            return await send_text(chat_id, f"Не смог отправить тест-пост:\n{exc}", reply_markup=admin_inline())
    return await send_text(chat_id, "Неизвестное действие админ-панели.", reply_markup=admin_inline())


async def setup_bot():
    await tg(
        "setMyCommands",
        {
            "commands": [
                {"command": "start", "description": "Открыть красивое меню"},
                {"command": "menu", "description": "Открыть меню"},
                {"command": "orig", "description": "Найти оригинал"},
                {"command": "remix", "description": "Найти ремиксы"},
                {"command": "find", "description": "Найти карточку трека"},
                {"command": "add", "description": "Опубликовать оригинал в канал"},
                {"command": "history", "description": "Показать историю публикаций"},
                {"command": "republish", "description": "Переопубликовать по video_id"},
                {"command": "admin", "description": "Админ-панель"},
                {"command": "help", "description": "Помощь"},
            ]
        },
    )


async def process_text_message(message):
    text = (message.get("text") or "").strip()
    chat_id = message["chat"]["id"]
    if not text:
        return

    if text == BTN_FIND:
        return await ask_for_query(chat_id, "orig")
    if text == BTN_REMIX:
        return await ask_for_query(chat_id, "remix")
    if text == BTN_PUBLISH:
        return await ask_for_query(chat_id, "publish")
    if text == BTN_HISTORY:
        return await handle_history(chat_id, "10")
    if text == BTN_ADMIN:
        return await show_admin_panel(chat_id)
    if text == BTN_HELP:
        return await send_text(chat_id, HELP_TEXT, reply_markup=main_menu_keyboard())
    if text in [BTN_MENU, BTN_CANCEL]:
        return await show_menu(chat_id)

    state = get_state(chat_id)
    if text.startswith("/"):
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@", 1)[0].lower()
        arg = arg.strip()

        if cmd in ["/start", "/menu"]:
            return await show_menu(chat_id)
        if cmd == "/help":
            return await send_text(chat_id, HELP_TEXT, reply_markup=main_menu_keyboard())
        if cmd == "/history":
            return await handle_history(chat_id, arg or "10")
        if cmd == "/republish":
            return await handle_republish(chat_id, arg)
        if cmd == "/admin":
            return await show_admin_panel(chat_id)
        if cmd in ["/orig", "/find"]:
            clear_state(chat_id)
            if not arg:
                return await ask_for_query(chat_id, "orig")
            return await handle_original(chat_id, arg)
        if cmd == "/remix":
            clear_state(chat_id)
            if not arg:
                return await ask_for_query(chat_id, "remix")
            return await handle_remix(chat_id, arg)
        if cmd == "/add":
            clear_state(chat_id)
            if not arg:
                return await ask_for_query(chat_id, "publish")
            return await handle_publish(chat_id, arg)
        return await send_text(chat_id, "Неизвестная команда. Нажми /menu.", reply_markup=main_menu_keyboard())

    if state == "orig":
        clear_state(chat_id)
        return await handle_original(chat_id, text)
    if state == "remix":
        clear_state(chat_id)
        return await handle_remix(chat_id, text)
    if state == "publish":
        clear_state(chat_id)
        return await handle_publish(chat_id, text)

    return await handle_original(chat_id, text)


async def process_callback(callback):
    callback_id = callback["id"]
    data = callback.get("data", "")
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")

    if data == "menu":
        await answer_callback(callback_id, "Открываю меню")
        return await show_menu(chat_id)

    if data.startswith("admin|"):
        await answer_callback(callback_id, "Открываю раздел")
        return await handle_admin_action(chat_id, data.split("|", 1)[1])

    parts = data.split("|")
    if len(parts) < 2:
        return await answer_callback(callback_id, "Некорректная кнопка", True)

    action, bundle_id = parts[0], parts[1]
    bundle_data = from_cache(bundle_id)
    if not bundle_data:
        return await answer_callback(callback_id, "Кэш истёк, повтори поиск", True)

    try:
        if action == "showr":
            await answer_callback(callback_id, "Показываю ремиксы")
            return await send_text(chat_id, remix_list_card(bundle_data["remix"], bundle_data["query"]), reply_markup=remixes_inline(bundle_data))
        if action == "sel":
            index = int(parts[2]) if len(parts) > 2 else 0
            if index >= len(bundle_data["orig"]):
                return await answer_callback(callback_id, "Вариант не найден", True)
            await answer_callback(callback_id, f"Выбран вариант {index + 1}")
            track = bundle_data["orig"][index]
            return await send_track_preview(
                chat_id,
                track,
                track_card(track, bundle_data["query"], f"✨ Оригинал #{index + 1}"),
                reply_markup=main_inline(bundle_data, index),
            )
        if action == "pubo":
            index = int(parts[2]) if len(parts) > 2 else 0
            if index >= len(bundle_data["orig"]):
                return await answer_callback(callback_id, "Вариант не найден", True)
            result = await publish(bundle_data["orig"][index], bundle_data["query"], "ORIGINAL", False)
            if result["status"] == "dup":
                await answer_callback(callback_id, "Уже публиковался", True)
                return await send_text(
                    chat_id,
                    duplicate_card(result["row"]),
                    reply_markup=inline(
                        [
                            [{"text": "▶️ Открыть", "url": result["row"]["url"]}],
                            [{"text": "🏠 Меню", "callback_data": "menu"}],
                        ]
                    ),
                )
            await answer_callback(callback_id, "Опубликовано")
            return await send_text(chat_id, "✅ Оригинал отправлен в канал.", reply_markup=main_menu_keyboard())
        if action == "pubr":
            index = int(parts[2]) if len(parts) > 2 else 0
            if index >= len(bundle_data["remix"]):
                return await answer_callback(callback_id, "Ремикс не найден", True)
            result = await publish(bundle_data["remix"][index], bundle_data["query"], "REMIX", False)
            if result["status"] == "dup":
                await answer_callback(callback_id, "Уже публиковался", True)
                return await send_text(
                    chat_id,
                    duplicate_card(result["row"]),
                    reply_markup=inline(
                        [
                            [{"text": "▶️ Открыть", "url": result["row"]["url"]}],
                            [{"text": "🏠 Меню", "callback_data": "menu"}],
                        ]
                    ),
                )
            await answer_callback(callback_id, "Ремикс опубликован")
            return await send_text(chat_id, "✅ Ремикс отправлен в канал.", reply_markup=main_menu_keyboard())
    except Exception:
        return await answer_callback(callback_id, "Ошибка. Проверь права бота и лог", True)


async def process_update(update):
    if "message" in update:
        return await process_text_message(update["message"])
    if "callback_query" in update:
        return await process_callback(update["callback_query"])
    return None


async def close_resources():
    await http.aclose()
    conn.close()
