# Webhook version for VPS

В репозиторий добавлен отдельный вход `webhook_main.py`. Он не ломает polling-версию из `main.py`.

## Что подготовлено

- `webhook_main.py` — HTTP webhook сервер для Telegram
- `.env.webhook.example` — переменные окружения под webhook
- `deploy/tg-music-bot-webhook.service` — systemd unit
- `deploy/nginx-tg-music-bot.conf` — пример nginx-конфига

## Быстрый запуск на VPS

```bash
cd /opt
git clone https://github.com/dgromov588-svg/tg-music-bot.git
cd tg-music-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.webhook.example .env
```

Заполни `.env`:

- `TELEGRAM_BOT_TOKEN`
- `YOUTUBE_API_KEY`
- `PUBLISH_CHAT_ID`
- `WEBHOOK_BASE_URL` — например `https://bot.example.com`
- `WEBHOOK_SECRET_PATH` — длинная случайная строка
- `WEBHOOK_SECRET_TOKEN` — длинная случайная строка

## Ручной старт

```bash
source .venv/bin/activate
python webhook_main.py
```

После запуска сервер поднимется на `WEBHOOK_HOST:WEBHOOK_PORT`.

## Проверка

```bash
curl http://127.0.0.1:8080/healthz
```

## systemd

Скопируй unit:

```bash
cp deploy/tg-music-bot-webhook.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable tg-music-bot-webhook
systemctl start tg-music-bot-webhook
systemctl status tg-music-bot-webhook
```

При необходимости поправь пути и пользователя внутри unit-файла.

## nginx

Скопируй конфиг:

```bash
cp deploy/nginx-tg-music-bot.conf /etc/nginx/sites-available/tg-music-bot.conf
ln -s /etc/nginx/sites-available/tg-music-bot.conf /etc/nginx/sites-enabled/tg-music-bot.conf
nginx -t
systemctl reload nginx
```

Замени `server_name` на свой домен.

## HTTPS

После того как домен смотрит на VPS:

```bash
apt install certbot python3-certbot-nginx -y
certbot --nginx -d bot.example.com
```

## Webhook

Если `WEBHOOK_BASE_URL` заполнен, бот сам попытается зарегистрировать webhook при старте.

Также можно вызвать вручную:

```bash
curl "https://bot.example.com/set-webhook?url=https://bot.example.com"
```

Удаление webhook:

```bash
curl "https://bot.example.com/delete-webhook"
```

## Маршруты

- `GET /healthz` — healthcheck
- `GET /set-webhook` — ручная регистрация webhook
- `GET /delete-webhook` — удалить webhook
- `POST /<WEBHOOK_SECRET_PATH>` — endpoint для Telegram

## Рекомендации

- держи `WEBHOOK_SECRET_PATH` и `WEBHOOK_SECRET_TOKEN` разными
- не публикуй `.env`
- в production лучше оставить `WEBHOOK_HOST=127.0.0.1` и проксировать только через nginx
- SQLite будет лежать в `data/music_bot.db`
