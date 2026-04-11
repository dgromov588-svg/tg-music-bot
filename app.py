import asyncio
import logging
import os
import threading
from typing import Any

from flask import Flask, abort, jsonify, request

from bot_core import process_update, setup_bot, tg

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = f"/{WEBHOOK_PATH}"

WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()

_loop = asyncio.new_event_loop()
_loop_thread: threading.Thread | None = None
_setup_lock = threading.Lock()
_setup_done = False


def _run_loop() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _ensure_loop() -> None:
    global _loop_thread
    if _loop_thread and _loop_thread.is_alive():
        return
    _loop_thread = threading.Thread(target=_run_loop, name="tg-music-bot-loop", daemon=True)
    _loop_thread.start()


def run_async(coro: Any):
    _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()


def ensure_setup() -> None:
    global _setup_done
    if _setup_done:
        return
    with _setup_lock:
        if _setup_done:
            return
        run_async(setup_bot())
        _setup_done = True
        logger.info("Bot setup completed")


app = Flask(__name__)


@app.get("/")
def index():
    return jsonify({"ok": True, "service": "tg-music-bot", "mode": "webhook"})


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post(WEBHOOK_PATH)
def webhook():
    ensure_setup()

    if WEBHOOK_SECRET_TOKEN:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != WEBHOOK_SECRET_TOKEN:
            abort(403)

    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        abort(400)

    run_async(process_update(update))
    return jsonify({"ok": True})


@app.post("/set-webhook")
def set_webhook():
    ensure_setup()

    admin_key = os.getenv("WEBHOOK_ADMIN_KEY", "").strip()
    if admin_key:
        supplied = request.headers.get("X-Webhook-Admin-Key", "")
        if supplied != admin_key:
            abort(403)

    base_url = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return jsonify({"ok": False, "error": "WEBHOOK_BASE_URL is empty"}), 500

    payload = {
        "url": f"{base_url}{WEBHOOK_PATH}",
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    }
    if WEBHOOK_SECRET_TOKEN:
        payload["secret_token"] = WEBHOOK_SECRET_TOKEN

    result = run_async(tg("setWebhook", payload))
    return jsonify({"ok": True, "result": result})


application = app
