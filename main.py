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
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в Secrets!")
if not ADMIN_CHAT_ID:
    raise ValueError("ADMIN_CHAT_ID не задан в Secrets!")

DB_PATH = "messages.db"


# --- БАЗА ДАННЫХ ---

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS connections (
            connection_id TEXT PRIMARY KEY,
            business_owner_id INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
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
    conn.commit()
    conn.close()


def save_connection(conn_id: str, owner_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO connections (connection_id, business_owner_id)
        VALUES (?, ?)
    """, (conn_id, owner_id))
    conn.commit()
    conn.close()


def get_connection_owner(conn_id: str):
    if not conn_id:
        return None
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT business_owner_id FROM connections WHERE connection_id = ?", (conn_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


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

    cursor.execute("""
        INSERT OR REPLACE INTO messages
        (chat_id, message_id, user_id, business_connection_id, is_from_owner,
         text, content_type, file_id, caption, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message.chat.id,
        message.message_id,
        message.from_user.id if message.from_user else 0,
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
        "SELECT chat_id, message_id, user_id, business_connection_id, is_from_owner, "
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


# --- БОТ ---

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Бот отслеживает удалённые сообщения в Telegram Business.\n\n"
        "Подключите меня в Настройках → Telegram Business → Чат-боты.\n\n"
        "Если один участник удалит сообщение — второй получит его текст."
    )


@dp.business_connection()
async def on_business_connection(connection: types.BusinessConnection):
    owner_id = connection.user.id
    save_connection(connection.id, owner_id)
    logging.info(f"🔌 Business подключён: {connection.id} → owner {owner_id}")


@dp.business_message()
async def on_business_message(message: types.Message):
    """Сохраняем каждое входящее сообщение и запоминаем, кто автор."""
    try:
        bc_id = getattr(message, "business_connection_id", None)
        business_owner_id = get_connection_owner(bc_id)
        author_id = message.from_user.id if message.from_user else 0
        is_from_owner = (author_id == business_owner_id)

        save_message(message, bc_id, is_from_owner)
        who = "хозяин бизнеса" if is_from_owner else "собеседник"
        logging.info(f"💾 Сохранено msg {message.message_id}, автор: {who}, чат {message.chat.id}")
    except Exception as e:
        logging.error(f"Save error: {e}")


@dp.edited_business_message()
async def on_edited_business_message(message: types.Message):
    try:
        bc_id = getattr(message, "business_connection_id", None)
        business_owner_id = get_connection_owner(bc_id)
        author_id = message.from_user.id if message.from_user else 0
        is_from_owner = (author_id == business_owner_id)
        save_message(message, bc_id, is_from_owner)
    except Exception as e:
        logging.error(f"Edit error: {e}")


@dp.deleted_business_messages()
async def on_deleted_business_messages(event: types.BusinessMessagesDeleted):
    """Удалил один — уведомление другому."""
    bc_id = getattr(event, "business_connection_id", None)
    logging.info(f"🗑 Удалено {len(event.message_ids)} в чате {event.chat.id}")

    for msg_id in event.message_ids:
        row = get_message(event.chat.id, msg_id)

        if not row:
            logging.warning(f"Msg {msg_id} не в БД")
            continue

        (chat_id, message_id, user_id, bc, is_from_owner,
         text, content_type, file_id, caption, date) = row

        if is_from_owner:
            # Удалил хозяин бизнеса → шлём собеседнику (в чат с бизнесом)
            target_id = chat_id
            use_business = True
            logging.info(f"→ Шлём СОБЕСЕДНИКУ {target_id} (удалил хозяин)")
        else:
            # Удалил собеседник → шлём хозяину (в личку с ботом)
            target_id = ADMIN_CHAT_ID
            use_business = False
            logging.info(f"→ Шлём ХОЗЯИНУ {target_id} (удалил собеседник)")

        header = f"🗑 Собеседник удалил сообщение\n🕒 {date}"

        try:
            kwargs = {"chat_id": target_id}
            if use_business and bc_id:
                kwargs["business_connection_id"] = bc_id

            if text:
                await bot.send_message(text=f"{header}\n\n💬 {text}", **kwargs)
            elif content_type == "photo" and file_id:
                await bot.send_photo(photo=file_id, caption=f"{header}\n📷 {caption}", **kwargs)
            elif content_type == "video" and file_id:
                await bot.send_video(video=file_id, caption=f"{header}\n🎥 {caption}", **kwargs)
            elif content_type == "document" and file_id:
                await bot.send_document(document=file_id, caption=f"{header}\n📄 {caption}", **kwargs)
            elif content_type == "voice" and file_id:
                await bot.send_voice(voice=file_id, caption=header, **kwargs)
            elif content_type == "audio" and file_id:
                await bot.send_audio(audio=file_id, caption=f"{header}\n🎵 {caption}", **kwargs)
            elif content_type == "sticker" and file_id:
                await bot.send_sticker(sticker=file_id, **kwargs)
                await bot.send_message(text=header, **kwargs)
            elif content_type == "video_note" and file_id:
                await bot.send_video_note(video_note=file_id, **kwargs)
                await bot.send_message(text=header, **kwargs)
            else:
                await bot.send_message(text=f"{header}\n⚠️ {content_type}", **kwargs)
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
    logging.info(f"🚀 Бот запущен, ADMIN_CHAT_ID={ADMIN_CHAT_ID}")
    asyncio.create_task(git_sync_loop())
    asyncio.create_task(periodic_cleanup())
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True
    )


if __name__ == "__main__":
    asyncio.run(main())
