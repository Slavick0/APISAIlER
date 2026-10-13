import asyncio
import logging
import sys
import sqlite3
import os
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

# Токен и админ берём ТОЛЬКО из секретов GitHub (в коде их нет!)
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
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            business_connection_id TEXT,
            text TEXT,
            content_type TEXT,
            file_id TEXT,
            caption TEXT,
            date TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bc ON messages(business_connection_id)")
    conn.commit()
    conn.close()


def save_message(message: types.Message, business_connection_id: str):
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
        (chat_id, message_id, user_id, business_connection_id, text, content_type, file_id, caption, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message.chat.id,
        message.message_id,
        message.from_user.id if message.from_user else 0,
        business_connection_id or "",
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
        "SELECT chat_id, message_id, user_id, business_connection_id, text, content_type, file_id, caption, date "
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


# --- СИНХРОНИЗАЦИЯ С GITHUB ---

async def git_sync_loop():
    """Каждую минуту коммитим БД в репозиторий."""
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
        "Подключите меня в Настройках → Telegram Business → Чат-боты.\n"
        "После подключения все удалённые сообщения будут приходить сюда."
    )


@dp.business_connection()
async def on_business_connection(connection: types.BusinessConnection):
    logging.info(f"🔌 Business подключён: {connection.id} → user {connection.user.id}")


@dp.business_message()
async def on_business_message(message: types.Message):
    try:
        bc_id = getattr(message, "business_connection_id", None)
        save_message(message, bc_id)
    except Exception as e:
        logging.error(f"Save error: {e}")


@dp.edited_business_message()
async def on_edited_business_message(message: types.Message):
    try:
        bc_id = getattr(message, "business_connection_id", None)
        save_message(message, bc_id)
    except Exception as e:
        logging.error(f"Edit error: {e}")


@dp.deleted_business_messages()
async def on_deleted_business_messages(event: types.BusinessMessagesDeleted):
    """Все удалённые сообщения шлём в ЛИЧКУ С БОТОМ (ADMIN_CHAT_ID)."""
    logging.info(f"🗑 Удалено {len(event.message_ids)} в чате {event.chat.id}")

    for msg_id in event.message_ids:
        row = get_message(event.chat.id, msg_id)

        if not row:
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"🗑 В чате {event.chat.id} удалено сообщение (ID {msg_id}), но текст не сохранён."
            )
            continue

        (chat_id, message_id, user_id, bc, text, content_type, file_id, caption, date) = row

        header = f"🗑 Удалено\n💬 Чат: {chat_id}\n🆔 От: {user_id}\n🕒 {date}"

        try:
            if text:
                await bot.send_message(ADMIN_CHAT_ID, f"{header}\n\n💬 {text}")
            elif content_type == "photo" and file_id:
                await bot.send_photo(ADMIN_CHAT_ID, file_id, caption=f"{header}\n📷 {caption}")
            elif content_type == "video" and file_id:
                await bot.send_video(ADMIN_CHAT_ID, file_id, caption=f"{header}\n🎥 {caption}")
            elif content_type == "document" and file_id:
                await bot.send_document(ADMIN_CHAT_ID, file_id, caption=f"{header}\n📄 {caption}")
            elif content_type == "voice" and file_id:
                await bot.send_voice(ADMIN_CHAT_ID, file_id, caption=header)
            elif content_type == "audio" and file_id:
                await bot.send_audio(ADMIN_CHAT_ID, file_id, caption=f"{header}\n🎵 {caption}")
            elif content_type == "sticker" and file_id:
                await bot.send_sticker(ADMIN_CHAT_ID, file_id)
                await bot.send_message(ADMIN_CHAT_ID, header)
            elif content_type == "video_note" and file_id:
                await bot.send_video_note(ADMIN_CHAT_ID, file_id)
                await bot.send_message(ADMIN_CHAT_ID, header)
            else:
                await bot.send_message(ADMIN_CHAT_ID, f"{header}\n⚠️ {content_type}")
        except Exception as e:
            logging.error(f"Send error: {e}")

        delete_message(event.chat.id, msg_id)


async def periodic_cleanup():
    while True:
        await asyncio.sleep(86400)
        try:
            cleanup_old_messages(days=3)
        except Exception as e:
            logging.error(f"Cleanup error: {e}")


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s [%(levelname)s] %(message)s")
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
