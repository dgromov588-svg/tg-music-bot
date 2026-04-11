import time
import bot_core as base

BOT = base.BOT

BTN_ARTIST = "🎤 Поиск по артисту"

base.conn.execute(
    "CREATE TABLE IF NOT EXISTS favorites("
    "id INTEGER PRIMARY KEY, video_id TEXT UNIQUE, title TEXT, channel TEXT, url TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
)
base.conn.execute(
    "CREATE TABLE IF NOT EXISTS blacklist("
    "id INTEGER PRIMARY KEY, video_id TEXT UNIQUE, title TEXT, channel TEXT, url TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
)
base.conn.commit()


def q1(sql, args=()):
    return base.conn.execute(sql, args).fetchone()


def qall(sql, args=()):
    return base.conn.execute(sql, args).fetchall()


def exec_sql(sql, args=()):
    cur = base.conn.execute(sql, args)
    base.conn.commit()
    return cur


def main_menu_keyboard():
    return {
        "keyboard": [
            [{"text": base.BTN_FIND}, {"text": base.BTN_REMIX}],
            [{"text": BTN_ARTIST}, {"text": base.BTN_PUBLISH}],
            [{"text": base.BTN_HISTORY}, {"text": base.BTN_ADMIN}],
            [{"text": base.BTN_HELP}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Напиши артиста и название трека…",
    }


def get_favorite(video_id):
    return q1("SELECT * FROM favorites WHERE video_id=?", (video_id,))


def get_blacklist(video_id):
    return q1("SELECT * FROM blacklist WHERE video_id=?", (video_id,))


def add_favorite(track):
    exec_sql(
        "INSERT OR REPLACE INTO favorites(video_id,title,channel,url) VALUES(?,?,?,?)",
        (track["video_id"], track["title"], track["channel"], track["url"]),
    )


def remove_favorite(video_id):
    exec_sql("DELETE FROM favorites WHERE video_id=?", (video_id,))


def add_blacklist(track):
    exec_sql(
        "INSERT OR REPLACE INTO blacklist(video_id,title,channel,url) VALUES(?,?,?,?)",
        (track["video_id"], track["title"], track["channel"], track["url"]),
    )


def remove_blacklist(video_id):
    exec_sql("DELETE FROM blacklist WHERE video_id=?", (video_id,))


def list_favorites(limit=10):
    return qall("SELECT * FROM favorites ORDER BY id DESC LIMIT ?", (limit,))


def list_blacklist(limit=10):
    return qall("SELECT * FROM blacklist ORDER BY id DESC LIMIT ?", (limit,))


def history_card(rows, title):
    lines = [f"{title}: {len(rows)}", ""]
    for i, row in enumerate(rows, 1):
        lines += [
            f"{i}. {row['title']}",
            f"   🆔 {row['video_id']}",
            f"   📺 {row['channel']}",
            f"   🗓 {row['created_at']}",
            "",
        ]
    return "\n".join(lines).strip()


def find_track(video_id):
    for _, data in base.cache.values():
        for source in ("orig", "remix", "artist"):
            for item in data.get(source, []):
                if item["video_id"] == video_id:
                    return item
    row = q1("SELECT * FROM pub WHERE video_id=? ORDER BY id DESC LIMIT 1", (video_id,))
    if row:
        return {"video_id": row["video_id"], "title": row["title"], "channel": row["channel"], "url": row["url"]}
    return None


def fav_blk_rows(track):
    return [[
        {
            "text": "⭐ Убрать из избранного" if get_favorite(track["video_id"]) else "⭐ В избранное",
            "callback_data": f"fav|{track['video_id']}",
        },
        {
            "text": "✅ Убрать из blacklist" if get_blacklist(track["video_id"]) else "🚫 В blacklist",
            "callback_data": f"blk|{track['video_id']}",
        },
    ]]


def original_inline(bundle_data, idx=0):
    total = len(bundle_data["orig"])
    idx = base.safe_index(bundle_data["orig"], idx)
    cur = bundle_data["orig"][idx]
    rows = [[
        {"text": "▶️ Открыть", "url": cur["url"]},
        {"text": "📢 В канал", "callback_data": f"pubo|{bundle_data['id']}|{idx}"},
    ]]
    nav = base.pager_nav_row("navo", bundle_data["id"], idx, total)
    if nav:
        rows.append(nav)
    nums = base.pager_number_row("navo", bundle_data["id"], idx, total)
    if nums:
        rows.append(nums)
    rows.extend(fav_blk_rows(cur))
    if bundle_data.get("artist"):
        rows.append([{"text": "✨ Автоподсказки", "callback_data": f"artistshow|{bundle_data['id']}"}])
    rows.append([
        {"text": "🔥 Ремиксы", "callback_data": f"showr|{bundle_data['id']}|0"},
        {"text": "🏠 Меню", "callback_data": "menu"},
    ])
    return base.inline(rows)


def remix_inline(bundle_data, idx=0):
    total = len(bundle_data["remix"])
    idx = base.safe_index(bundle_data["remix"], idx)
    cur = bundle_data["remix"][idx]
    rows = [[
        {"text": "▶️ Открыть", "url": cur["url"]},
        {"text": "📢 В канал", "callback_data": f"pubr|{bundle_data['id']}|{idx}"},
    ]]
    nav = base.pager_nav_row("navr", bundle_data["id"], idx, total)
    if nav:
        rows.append(nav)
    nums = base.pager_number_row("navr", bundle_data["id"], idx, total)
    if nums:
        rows.append(nums)
    rows.extend(fav_blk_rows(cur))
    rows.append([
        {"text": "🎧 Оригиналы", "callback_data": f"showo|{bundle_data['id']}|0"},
        {"text": "🏠 Меню", "callback_data": "menu"},
    ])
    return base.inline(rows)


def artist_inline(bundle_data):
    rows = []
    for i, _ in enumerate(bundle_data["artist"][:5]):
        rows.append([{"text": f"{i + 1}", "callback_data": f"artistpick|{bundle_data['id']}|{i}"}])
    rows.append([
        {"text": "🎧 Лучший вариант", "callback_data": f"showo|{bundle_data['id']}|0"},
        {"text": "🏠 Меню", "callback_data": "menu"},
    ])
    return base.inline(rows)


def track_caption(track, query, title, idx, total):
    text = base.track_card(track, query, title, idx, total)
    if get_favorite(track["video_id"]):
        text += "\n⭐ В избранном"
    if get_blacklist(track["video_id"]):
        text += "\n🚫 В blacklist"
    return text


async def show_menu(chat_id, text=None):
    base.clear_state(chat_id)
    return await base.send_text(chat_id, text or base.WELCOME_TEXT, reply_markup=main_menu_keyboard())


async def show_original(chat_id, bundle_data, idx=0):
    if not bundle_data["orig"]:
        return await base.send_text(chat_id, "😕 Ничего не нашёл.", reply_markup=main_menu_keyboard())
    idx = base.safe_index(bundle_data["orig"], idx)
    track = bundle_data["orig"][idx]
    return await base.send_track_preview(
        chat_id,
        track,
        track_caption(track, bundle_data["query"], "✨ Оригинал", idx, len(bundle_data["orig"])),
        reply_markup=original_inline(bundle_data, idx),
    )


async def show_remix(chat_id, bundle_data, idx=0):
    if not bundle_data["remix"]:
        return await base.send_text(chat_id, "😕 Ремиксы не нашёл.", reply_markup=main_menu_keyboard())
    idx = base.safe_index(bundle_data["remix"], idx)
    track = bundle_data["remix"][idx]
    return await base.send_track_preview(
        chat_id,
        track,
        track_caption(track, bundle_data["query"], "🔥 Ремикс", idx, len(bundle_data["remix"])),
        reply_markup=remix_inline(bundle_data, idx),
    )


async def artist_bundle(name):
    data = await base.bundle(f"{name} official audio")
    data["query"] = name
    data["artist"] = data["orig"][:5]
    return data


async def show_artist(chat_id, bundle_data):
    if not bundle_data["artist"]:
        return await base.send_text(chat_id, "😕 По артисту ничего не нашёл.", reply_markup=main_menu_keyboard())
    lines = [f"🎤 Поиск по артисту: {bundle_data['query']}", "", "✨ Автоподсказки:"]
    for i, track in enumerate(bundle_data["artist"][:5], 1):
        lines += [f"{i}. {track['title']}", f"   📺 {track['channel']}", f"   ⏱ {base.fmt_duration(track['secs'])}"]
    return await base.send_text(chat_id, "\n".join(lines), reply_markup=artist_inline(bundle_data))


async def publish(track, query, label, allow=False):
    blk = get_blacklist(track["video_id"])
    if blk:
        return {"status": "blacklisted", "message": f"🚫 Этот трек в blacklist.\n\n🎵 {blk['title']}\n📺 {blk['channel']}\n🆔 {blk['video_id']}"}
    return await base.publish(track, query, label, allow)


async def toggle_favorite(video_id):
    track = find_track(video_id)
    if not track:
        return "missing"
    if get_favorite(video_id):
        remove_favorite(video_id)
        return "removed"
    add_favorite(track)
    return "added"


async def toggle_blacklist(video_id):
    track = find_track(video_id)
    if not track:
        return "missing"
    if get_blacklist(video_id):
        remove_blacklist(video_id)
        return "removed"
    add_blacklist(track)
    return "added"


async def handle_favorites(chat_id, arg="10"):
    try:
        n = max(1, min(50, int(arg or "10")))
    except Exception:
        return await base.send_text(chat_id, "Пример: /favorites 10", reply_markup=main_menu_keyboard())
    rows = list_favorites(n)
    if not rows:
        return await base.send_text(chat_id, "⭐ Избранное пока пустое.", reply_markup=main_menu_keyboard())
    return await base.send_text(chat_id, history_card(rows, "⭐ Избранное"), reply_markup=main_menu_keyboard())


async def handle_blacklist(chat_id, arg="10"):
    try:
        n = max(1, min(50, int(arg or "10")))
    except Exception:
        return await base.send_text(chat_id, "Пример: /blacklist 10", reply_markup=main_menu_keyboard())
    rows = list_blacklist(n)
    if not rows:
        return await base.send_text(chat_id, "🚫 Blacklist пока пуст.", reply_markup=main_menu_keyboard())
    return await base.send_text(chat_id, history_card(rows, "🚫 Blacklist"), reply_markup=main_menu_keyboard())


async def show_admin_panel(chat_id):
    if not base.is_admin(chat_id):
        return await base.send_text(chat_id, "⛔️ Нет доступа к админ-панели.", reply_markup=main_menu_keyboard())
    total_posts = q1("SELECT COUNT(*) AS c FROM pub")["c"]
    unique_videos = q1("SELECT COUNT(DISTINCT video_id) AS c FROM pub")["c"]
    favorites_count = q1("SELECT COUNT(*) AS c FROM favorites")["c"]
    blacklist_count = q1("SELECT COUNT(*) AS c FROM blacklist")["c"]
    text = (
        "⚙️ Админ-панель\n\n"
        f"📢 Канал публикации: {base.PUB}\n"
        f"🗃 База: {base.DB}\n"
        f"🧾 Всего публикаций: {total_posts}\n"
        f"🎬 Уникальных видео: {unique_videos}\n"
        f"⭐ Избранное: {favorites_count}\n"
        f"🚫 Blacklist: {blacklist_count}"
    )
    return await base.send_text(chat_id, text, reply_markup=base.admin_inline())


async def handle_admin_action(chat_id, action):
    if action == "favorites":
        return await handle_favorites(chat_id, "10")
    if action == "blacklist":
        return await handle_blacklist(chat_id, "10")
    return await base.handle_admin_action(chat_id, action)


async def setup_bot():
    await base.tg(
        "setMyCommands",
        {"commands": [
            {"command": "start", "description": "Открыть красивое меню"},
            {"command": "menu", "description": "Открыть меню"},
            {"command": "orig", "description": "Найти оригинал"},
            {"command": "remix", "description": "Найти ремиксы"},
            {"command": "artist", "description": "Поиск по артисту"},
            {"command": "find", "description": "Найти карточку трека"},
            {"command": "add", "description": "Опубликовать оригинал в канал"},
            {"command": "history", "description": "Показать историю публикаций"},
            {"command": "favorites", "description": "Показать избранное"},
            {"command": "blacklist", "description": "Показать blacklist"},
            {"command": "republish", "description": "Переопубликовать по video_id"},
            {"command": "admin", "description": "Админ-панель"},
            {"command": "help", "description": "Помощь"},
        ]},
    )


async def process_text_message(message):
    text = (message.get("text") or "").strip()
    chat_id = message["chat"]["id"]
    if not text:
        return

    if text == BTN_ARTIST:
        return await base.ask_for_query(chat_id, "artist")
    if text == base.BTN_FIND:
        return await base.ask_for_query(chat_id, "orig")
    if text == base.BTN_REMIX:
        return await base.ask_for_query(chat_id, "remix")
    if text == base.BTN_PUBLISH:
        return await base.ask_for_query(chat_id, "publish")
    if text == base.BTN_HISTORY:
        return await base.handle_history(chat_id, "10")
    if text == base.BTN_ADMIN:
        return await show_admin_panel(chat_id)
    if text == base.BTN_HELP:
        return await base.send_text(chat_id, HELP_TEXT, reply_markup=main_menu_keyboard())
    if text in [base.BTN_MENU, base.BTN_CANCEL]:
        return await show_menu(chat_id)

    state = base.get_state(chat_id)
    if text.startswith("/"):
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@", 1)[0].lower()
        arg = arg.strip()

        if cmd in ["/start", "/menu"]:
            return await show_menu(chat_id)
        if cmd == "/help":
            return await base.send_text(chat_id, HELP_TEXT, reply_markup=main_menu_keyboard())
        if cmd == "/history":
            return await base.handle_history(chat_id, arg or "10")
        if cmd == "/favorites":
            return await handle_favorites(chat_id, arg or "10")
        if cmd == "/blacklist":
            return await handle_blacklist(chat_id, arg or "10")
        if cmd == "/republish":
            return await base.handle_republish(chat_id, arg)
        if cmd == "/admin":
            return await show_admin_panel(chat_id)
        if cmd in ["/orig", "/find"]:
            base.clear_state(chat_id)
            if not arg:
                return await base.ask_for_query(chat_id, "orig")
            data = await base.bundle(arg)
            return await show_original(chat_id, data, 0)
        if cmd == "/remix":
            base.clear_state(chat_id)
            if not arg:
                return await base.ask_for_query(chat_id, "remix")
            data = await base.bundle(arg)
            return await show_remix(chat_id, data, 0)
        if cmd == "/artist":
            base.clear_state(chat_id)
            if not arg:
                return await base.ask_for_query(chat_id, "artist")
            return await show_artist(chat_id, await artist_bundle(arg))
        if cmd == "/add":
            base.clear_state(chat_id)
            if not arg:
                return await base.ask_for_query(chat_id, "publish")
            data = await base.bundle(arg)
            if not data["orig"]:
                return await base.send_text(chat_id, "😕 Ничего не нашёл для публикации.", reply_markup=main_menu_keyboard())
            result = await publish(data["orig"][0], arg, "ORIGINAL", False)
            if result["status"] == "blacklisted":
                return await base.send_text(chat_id, result["message"], reply_markup=main_menu_keyboard())
            return await base.handle_publish(chat_id, arg)
        return await base.send_text(chat_id, "Неизвестная команда. Нажми /menu.", reply_markup=main_menu_keyboard())

    if state == "artist":
        base.clear_state(chat_id)
        return await show_artist(chat_id, await artist_bundle(text))

    return await base.process_text_message(message)


async def process_callback(callback):
    callback_id = callback["id"]
    data = callback.get("data", "")
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")

    if data == "menu":
        await base.answer_callback(callback_id, "Открываю меню")
        return await show_menu(chat_id)

    if data.startswith("admin|"):
        await base.answer_callback(callback_id, "Открываю раздел")
        return await handle_admin_action(chat_id, data.split("|", 1)[1])

    if data.startswith("fav|"):
        result = await toggle_favorite(data.split("|", 1)[1])
        if result == "missing":
            return await base.answer_callback(callback_id, "Не нашёл трек", True)
        return await base.answer_callback(callback_id, "Добавил в избранное" if result == "added" else "Убрал из избранного")

    if data.startswith("blk|"):
        result = await toggle_blacklist(data.split("|", 1)[1])
        if result == "missing":
            return await base.answer_callback(callback_id, "Не нашёл трек", True)
        return await base.answer_callback(callback_id, "Добавил в blacklist" if result == "added" else "Убрал из blacklist")

    parts = data.split("|")
    if len(parts) >= 2:
        action, bundle_id = parts[0], parts[1]
        bundle_data = base.from_cache(bundle_id)
        if bundle_data:
            if action == "artistshow":
                await base.answer_callback(callback_id, "Показываю автоподсказки")
                return await show_artist(chat_id, bundle_data)
            if action == "artistpick":
                index = int(parts[2]) if len(parts) > 2 else 0
                await base.answer_callback(callback_id, f"Выбрал вариант {index + 1}")
                return await show_original(chat_id, bundle_data, index)
            if action == "showo":
                index = int(parts[2]) if len(parts) > 2 else 0
                await base.answer_callback(callback_id, "Показываю оригиналы")
                return await show_original(chat_id, bundle_data, index)
            if action == "showr":
                index = int(parts[2]) if len(parts) > 2 else 0
                await base.answer_callback(callback_id, "Показываю ремиксы")
                return await show_remix(chat_id, bundle_data, index)
            if action == "navo":
                index = int(parts[2]) if len(parts) > 2 else 0
                await base.answer_callback(callback_id, f"Оригинал {base.safe_index(bundle_data['orig'], index) + 1}")
                return await show_original(chat_id, bundle_data, index)
            if action == "navr":
                index = int(parts[2]) if len(parts) > 2 else 0
                await base.answer_callback(callback_id, f"Ремикс {base.safe_index(bundle_data['remix'], index) + 1}")
                return await show_remix(chat_id, bundle_data, index)
            if action == "pubo":
                index = int(parts[2]) if len(parts) > 2 else 0
                index = base.safe_index(bundle_data["orig"], index)
                result = await publish(bundle_data["orig"][index], bundle_data["query"], "ORIGINAL", False)
                if result["status"] == "blacklisted":
                    await base.answer_callback(callback_id, "Трек в blacklist", True)
                    return await base.send_text(chat_id, result["message"], reply_markup=main_menu_keyboard())
            if action == "pubr":
                index = int(parts[2]) if len(parts) > 2 else 0
                index = base.safe_index(bundle_data["remix"], index)
                result = await publish(bundle_data["remix"][index], bundle_data["query"], "REMIX", False)
                if result["status"] == "blacklisted":
                    await base.answer_callback(callback_id, "Трек в blacklist", True)
                    return await base.send_text(chat_id, result["message"], reply_markup=main_menu_keyboard())

    return await base.process_callback(callback)


async def close_resources():
    await base.close_resources()
