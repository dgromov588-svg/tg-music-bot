# Webhook Plus setup

Это инструкция для запуска расширенной визуальной версии бота через `webhook_plus.py`.

## Что использовать

- `bot_plus.py` — расширенная логика
- `webhook_plus.py` — webhook entrypoint
- `deploy/tg-music-bot-webhook-plus.service` — systemd unit

## Быстрое обновление на VPS

```bash
cd /opt/tg-music-bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
cp deploy/tg-music-bot-webhook-plus.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable tg-music-bot-webhook-plus
systemctl restart tg-music-bot-webhook-plus
systemctl status tg-music-bot-webhook-plus
```

## Что должно быть в `.env`

```env
TELEGRAM_BOT_TOKEN=...
YOUTUBE_API_KEY=...
PUBLISH_CHAT_ID=...
WEBHOOK_BASE_URL=https://bot.example.com
WEBHOOK_SECRET_PATH=long_random_path
WEBHOOK_SECRET_TOKEN=long_random_token
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8080
ADMIN_USER_IDS=123456789,987654321
```

## Nginx

Можно использовать тот же reverse proxy, что и для обычной webhook-версии.
Если nginx уже проксирует на `127.0.0.1:8080`, менять его не нужно.

## Проверка

```bash
curl http://127.0.0.1:8080/healthz
```

## Полезно

Остановить старую версию, если она ещё висит:

```bash
systemctl stop tg-music-bot-webhook
systemctl disable tg-music-bot-webhook
```

Запустить новую:

```bash
systemctl enable tg-music-bot-webhook-plus
systemctl start tg-music-bot-webhook-plus
```
