import asyncio
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from bot_core import BOT, close_resources, process_update, setup_bot, tg


WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
WEBHOOK_SECRET_PATH = os.getenv("WEBHOOK_SECRET_PATH", "").strip() or secrets.token_urlsafe(24)
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
DROP_PENDING_UPDATES = os.getenv("DROP_PENDING_UPDATES", "true").strip().lower() in {"1", "true", "yes", "on"}


async def configure_webhook():
    await setup_bot()
    await tg("deleteWebhook", {"drop_pending_updates": DROP_PENDING_UPDATES})
    if not WEBHOOK_BASE_URL:
        print("WEBHOOK_BASE_URL не указан. Сервер стартует без регистрации webhook.")
        print(f"Добавь WEBHOOK_BASE_URL и зарегистрируй webhook на путь /{WEBHOOK_SECRET_PATH}")
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
    server_version = "TgMusicBotWebhook/2.0"

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
            return self._send_json(200, {"ok": True, "service": "tg-music-bot-webhook", "bot": BOT[:10] + "..."})
        if parsed.path == "/set-webhook":
            params = parse_qs(parsed.query)
            override_url = (params.get("url", [""])[0] or WEBHOOK_BASE_URL).rstrip("/")
            if not override_url:
                return self._send_json(400, {"ok": False, "error": "missing url"})
            payload = {
                "url": f"{override_url}/{WEBHOOK_SECRET_PATH}",
                "drop_pending_updates": DROP_PENDING_UPDATES,
                "allowed_updates": ["message", "callback_query"],
            }
            if WEBHOOK_SECRET_TOKEN:
                payload["secret_token"] = WEBHOOK_SECRET_TOKEN
            try:
                asyncio.run(tg("setWebhook", payload))
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
            token = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if token != WEBHOOK_SECRET_TOKEN:
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
        try:
            asyncio.run(close_resources())
        except Exception:
            pass


if __name__ == "__main__":
    main()
