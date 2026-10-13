import asyncio
import logging
import sys
import sqlite3
import os
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в Secrets!")

DB_PATH = "messages.db"


# --- БАЗА ДАННЫХ ---

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            user_name TEXT,
            user_username TEXT,
            business_connection_id TEXT,
            is_from_owner INTEGER,
            text TEXT,
            content_type TEXT,
            file_id TEXT,
            caption TEXT,
            date TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
    """)
    for col in ["is_from_owner", "user_name", "user_username", "business_connection_id"]:
        try:
            cursor.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def save_message(message: types.Message, business_connection_id: str, is_from_owner: bool):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.document:
        file_id = message.document.file_id
    elif message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.sticker:
        file_id = message.sticker.file_id
    elif message.video_note:
        file_id = message.video_note.file_id

    user = message.from_user
    user_name = user.full_name if user else "Неизвестный"
    user_username = (user.username if user and user.username else "")

    cursor.execute("""
        INSERT OR REPLACE INTO messages
        (chat_id, message_id, user_id, user_name, user_username,
         business_connection_id, is_from_owner,
         text, content_type, file_id, caption, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message.chat.id,
        message.message_id,
        user.id if user else 0,
        user_name,
        user_username,
        business_connection_id or "",
        1 if is_from_owner else 0,
        message.text or "",
        message.content_type,
        file_id,
        message.caption or "",
        message.date.isoformat() if message.date else datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def get_message(chat_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT chat_id, message_id, user_id, user_name, user_username, "
        "business_connection_id, is_from_owner, "
        "text, content_type, file_id, caption, date "
        "FROM messages WHERE chat_id = ? AND message_id = ?",
        (chat_id, message_id)
    )
    row = cursor.fetchone()
    conn.close()
    return row


def delete_message(chat_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE chat_id = ? AND message_id = ?", (chat_id, message_id))
    conn.commit()
    conn.close()


def cleanup_old_messages(days: int = 3):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE date < datetime('now', ?)", (f'-{days} days',))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    logging.info(f"🧹 Очистка: удалено {deleted} старых записей")


# --- GIT СИНХРОНИЗАЦИЯ ---

async def git_sync_loop():
    while True:
        await asyncio.sleep(60)
        try:
            subprocess.run(["git", "config", "user.email", "bot@example.com"], check=True)
            subprocess.run(["git", "config", "user.name", "Bot"], check=True)
            subprocess.run(["git", "add", DB_PATH], check=True)
            result = subprocess.run(
                ["git", "commit", "-m", f"Update DB {datetime.now().isoformat()}"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                subprocess.run(["git", "push"], check=True)
                logging.info("📤 БД синхронизирована с GitHub")
        except Exception as e:
            logging.error(f"Git sync error: {e}")


# --- УТИЛИТЫ ---

def format_time(iso_date: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime("%d.%m.%Y | %H:%M:%S")
    except Exception:
        return iso_date


def get_type_label(content_type: str) -> str:
    labels = {
        "text": "текстовое сообщение",
        "photo": "фото",
        "video": "видео",
        "document": "документ",
        "voice": "голосовое сообщение",
        "audio": "аудио",
        "sticker": "стикер",
        "video_note": "видеосообщение",
        "animation": "GIF",
    }
    return labels.get(content_type, content_type)


def build_header(user_name: str, user_username: str, user_id: int,
                 chat_id: int, date_iso: str, content_type: str,
                 is_from_owner: bool) -> str:
    type_label = get_type_label(content_type)
    if is_from_owner:
        display_name = "Вы"
    else:
        display_name = user_name or "Неизвестный"
        if user_username:
            display_name += f" (@{user_username})"

    return (
        f"🗑 Удалено {type_label}\n"
        f"👤 От:     {display_name}\n"
        f"🆔 User ID: {user_id}\n"
        f"💬 Chat ID: {chat_id}\n"
        f"🕒 Время:  {format_time(date_iso)}"
    )


# --- БОТ ---

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Бот следит за удалёнными сообщениями.\n\n"
        "Если собеседник удалит сообщение — вы получите его текст здесь."
    )


@dp.business_connection()
async def on_business_connection(connection: types.BusinessConnection):
    logging.info(f"🔌 Business подключён: {connection.id} → owner {connection.user.id}")


@dp.business_message()
async def on_business_message(message: types.Message):
    try:
        bc_id = getattr(message, "business_connection_id", None)
        business_owner_id = None
        if bc_id:
            try:
                conn_info = await bot.get_business_connection(bc_id)
                business_owner_id = conn_info.user.id
            except Exception as e:
                logging.error(f"get_business_connection error: {e}")

        author_id = message.from_user.id if message.from_user else 0
        is_from_owner = (author_id == business_owner_id) if business_owner_id else False

        save_message(message, bc_id, is_from_owner)
        who = "владелец" if is_from_owner else "собеседник"
        logging.info(f"💾 Сохранено msg {message.message_id}, автор: {who}, чат {message.chat.id}")
    except Exception as e:
        logging.error(f"Save error: {e}")


@dp.edited_business_message()
async def on_edited_business_message(message: types.Message):
    try:
        bc_id = getattr(message, "business_connection_id", None)
        business_owner_id = None
        if bc_id:
            try:
                conn_info = await bot.get_business_connection(bc_id)
                business_owner_id = conn_info.user.id
            except Exception as e:
                logging.error(f"get_business_connection error: {e}")
        author_id = message.from_user.id if message.from_user else 0
        is_from_owner = (author_id == business_owner_id) if business_owner_id else False
        save_message(message, bc_id, is_from_owner)
    except Exception as e:
        logging.error(f"Edit error: {e}")


async def send_copy(chat_id: int, header: str,
                    text: str, content_type: str, file_id: str | None, caption: str):
    """Отправляет уведомление в ЛИЧНЫЙ ЧАТ С БОТОМ (без business_connection_id)."""
    kwargs = {"chat_id": chat_id}

    if content_type == "text" and text:
        await bot.send_message(text=f"{header}\n\n📝 Текст сообщения:\n{text}", **kwargs)
    elif content_type == "photo" and file_id:
        cap = f"{header}\n\n📝 Подпись:\n{caption}" if caption else header
        await bot.send_photo(photo=file_id, caption=cap, **kwargs)
    elif content_type == "video" and file_id:
        cap = f"{header}\n\n📝 Подпись:\n{caption}" if caption else header
        await bot.send_video(video=file_id, caption=cap, **kwargs)
    elif content_type == "document" and file_id:
        cap = f"{header}\n\n📝 Подпись:\n{caption}" if caption else header
        await bot.send_document(document=file_id, caption=cap, **kwargs)
    elif content_type == "voice" and file_id:
        await bot.send_voice(voice=file_id, caption=header, **kwargs)
    elif content_type == "audio" and file_id:
        cap = f"{header}\n\n📝 Подпись:\n{caption}" if caption else header
        await bot.send_audio(audio=file_id, caption=cap, **kwargs)
    elif content_type == "sticker" and file_id:
        await bot.send_sticker(sticker=file_id, **kwargs)
        await bot.send_message(text=header, **kwargs)
    elif content_type == "video_note" and file_id:
        await bot.send_video_note(video_note=file_id, **kwargs)
        await bot.send_message(text=header, **kwargs)
    elif content_type == "animation" and file_id:
        cap = f"{header}\n\n📝 Подпись:\n{caption}" if caption else header
        await bot.send_animation(animation=file_id, caption=cap, **kwargs)
    else:
        await bot.send_message(text=f"{header}\n\n⚠️ Тип: {content_type}", **kwargs)


@dp.deleted_business_messages()
async def on_deleted_business_messages(event: types.BusinessMessagesDeleted):
    bc_id = getattr(event, "business_connection_id", None)

    business_owner_id = None
    if bc_id:
        try:
            conn_info = await bot.get_business_connection(bc_id)
            business_owner_id = conn_info.user.id
            logging.info(f"👤 Владелец соединения: {business_owner_id}")
        except Exception as e:
            logging.error(f"get_business_connection error: {e}")

    if not business_owner_id:
        logging.error("Не удалось определить владельца — пропускаем")
        return

    logging.info(f"🗑 Удалено {len(event.message_ids)} в чате {event.chat.id}")

    for msg_id in event.message_ids:
        row = get_message(event.chat.id, msg_id)

        if not row:
            logging.warning(f"Msg {msg_id} не в БД")
            continue

        (chat_id, message_id, user_id, user_name, user_username,
         bc, is_from_owner, text, content_type, file_id, caption, date) = row

        header = build_header(
            user_name=user_name or "Неизвестный",
            user_username=user_username or "",
            user_id=user_id,
            chat_id=chat_id,
            date_iso=date,
            content_type=content_type,
            is_from_owner=bool(is_from_owner)
        )

        # ВСЕ уведомления идут ТОЛЬКО владельцу Y в ЛИЧНЫЙ ЧАТ С БОТОМ.
        # Независимо от того, кто удалил (X или Y).
        # business_connection_id НЕ передаём — тогда Telegram доставляет
        # сообщение в чат бота с Y, а не в бизнес-чат с X.
        target_id = business_owner_id

        logging.info(f"→ Шлём в личку с ботом: {target_id}")

        try:
            await send_copy(
                chat_id=target_id,
                header=header,
                text=text, content_type=content_type,
                file_id=file_id, caption=caption
            )
            logging.info(f"✅ Отправлено {target_id}")
        except Exception as e:
            logging.error(f"Send error (target={target_id}): {e}")

        delete_message(event.chat.id, msg_id)


async def periodic_cleanup():
    while True:
        await asyncio.sleep(86400)
        try:
            cleanup_old_messages(days=3)
        except Exception as e:
            logging.error(f"Cleanup error: {e}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    init_db()
    logging.info("🚀 Бот запущен")
    asyncio.create_task(git_sync_loop())
    asyncio.create_task(periodic_cleanup())
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True
    )


if __name__ == "__main__":
    asyncio.run(main())
