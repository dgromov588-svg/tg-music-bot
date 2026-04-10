# Telegram Music Finder Bot

Репозиторий содержит рабочий Telegram-бот для поиска музыкальных треков через YouTube Data API.

## Возможности

- `/orig <запрос>` — ищет лучший кандидат на оригинальную версию трека
- `/remix <запрос>` — показывает ремиксы
- `/find <запрос>` — показывает лучший результат и inline-кнопки
- `/add <запрос>` — публикует оригинал в канал
- `/history [N]` — история публикаций из SQLite
- `/republish <video_id>` — повторная публикация ранее найденного ролика
- защита от дублей по `video_id`

## Файлы

- `main.py` — основной код бота
- `.env.example` — шаблон переменных окружения
- `requirements.txt` — зависимости
- `Dockerfile` — контейнеризация

## Настройка

1. Создай Telegram-бота через `@BotFather`
2. Получи `TELEGRAM_BOT_TOKEN`
3. В Google Cloud включи `YouTube Data API v3`
4. Создай `YOUTUBE_API_KEY`
5. Добавь бота в канал и выдай право на публикацию сообщений
6. Скопируй `.env.example` в `.env`
7. Запусти:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Docker

```bash
docker build -t tg-music-bot .
docker run --env-file .env -v $(pwd)/data:/app/data tg-music-bot
```

## Ограничения

- Поиск идёт через YouTube Data API, а не отдельный публичный API YouTube Music
- Бот не скачивает и не перезаливает чужой аудиоконтент
- Для публикации в канал бот должен быть администратором
