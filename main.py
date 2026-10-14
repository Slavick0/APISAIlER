import asyncio
import logging
import sys
import sqlite3
import os
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.methods import DeleteBusinessMessages

# --- ИМПОРТ ДЛЯ DEEPSEEK (через OpenAI SDK) ---
from openai import OpenAI

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в Secrets!")
if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY не задан в Secrets!")

# Настройки ИИ
AI_ENABLED = True
AI_MODEL = "deepseek-flash"
AI_SYSTEM_PROMPT = (
    "Ты — вежливый и краткий ассистент в переписке Telegram. "
    "Отвечай на русском языке, дружелюбно, не более 2-3 предложений. "
    "Не упоминай, что ты ИИ, если не спросят напрямую."
)

# --- ИНИЦИАЛИЗАЦИЯ КЛИЕНТА DEEPSEEK ---
deepseek_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

DB_PATH = "messages.db"
SPAM_MAX = 20
SPAM_DELAY = 0.7


# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER, message_id INTEGER, user_id INTEGER, user_name TEXT,
            user_username TEXT, business_connection_id TEXT, is_from_owner INTEGER,
            text TEXT, content_type TEXT, file_id TEXT, caption TEXT, date TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_commands (
            chat_id INTEGER, message_id INTEGER, processed_at TEXT,
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

def is_command_processed(chat_id: int, message_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_commands WHERE chat_id = ? AND message_id = ?", (chat_id, message_id))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def mark_command_processed(chat_id: int, message_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO processed_commands (chat_id, message_id, processed_at) VALUES (?, ?, ?)",
                   (chat_id, message_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def save_message(message: types.Message, business_connection_id: str, is_from_owner: bool,
                 fallback_user_id: int = 0, fallback_user_name: str = "Бот", fallback_user_username: str = ""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    file_id = None
    if message.photo: file_id = message.photo[-1].file_id
    elif message.video: file_id = message.video.file_id
    elif message.document: file_id = message.document.file_id
    elif message.voice: file_id = message.voice.file_id
    elif message.audio: file_id = message.audio.file_id
    elif message.sticker: file_id = message.sticker.file_id
    elif message.video_note: file_id = message.video_note.file_id

    user = message.from_user
    if user:
        user_id, user_name, user_username = user.id, user.full_name, user.username or ""
    else:
        user_id, user_name, user_username = fallback_user_id, fallback_user_name, fallback_user_username

    cursor.execute("""
        INSERT OR REPLACE INTO messages
        (chat_id, message_id, user_id, user_name, user_username, business_connection_id,
         is_from_owner, text, content_type, file_id, caption, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (message.chat.id, message.message_id, user_id, user_name, user_username,
          business_connection_id or "", 1 if is_from_owner else 0, message.text or "",
          message.content_type, file_id, message.caption or "", message.date.isoformat() if message.date else datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_message(chat_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, message_id, user_id, user_name, user_username, business_connection_id, is_from_owner, text, content_type, file_id, caption, date FROM messages WHERE chat_id = ? AND message_id = ?", (chat_id, message_id))
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
    cursor.execute("DELETE FROM processed_commands WHERE processed_at < datetime('now', ?)", (f'-{days} days',))
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
            result = subprocess.run(["git", "commit", "-m", f"Update DB {datetime.now().isoformat()}"], capture_output=True, text=True)
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
    labels = {"text": "текстовое сообщение", "photo": "фото", "video": "видео", "document": "документ",
              "voice": "голосовое сообщение", "audio": "аудио", "sticker": "стикер",
              "video_note": "видеосообщение", "animation": "GIF"}
    return labels.get(content_type, content_type)

def build_header(user_name: str, user_username: str, user_id: int, chat_id: int, date_iso: str, content_type: str, is_from_owner: bool) -> str:
    type_label = get_type_label(content_type)
    if is_from_owner:
        display_name = "Вы"
    else:
        display_name = user_name or "Неизвестный"
        if user_username:
            display_name += f" (@{user_username})"
    return (f"🗑 Удалено {type_label}\n👤 От:     {display_name}\n🆔 User ID: {user_id}\n"
            f"💬 Chat ID: {chat_id}\n🕒 Время:  {format_time(date_iso)}")

# --- DEEPSEEK АВТО-ОТВЕТ ---
async def get_ai_reply(user_text: str) -> str | None:
    """Получает ответ от DeepSeek через OpenAI-совместимый API."""
    if not AI_ENABLED or not deepseek_client:
        return None
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: deepseek_client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.7,
                max_tokens=300,
                stream=False
            )
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"DeepSeek API error: {type(e).__name__}: {e}")
        return None

# --- КОМАНДА .spam ---
async def handle_spam_command(message: types.Message, bc_id: str, is_from_owner: bool, owner_id: int):
    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    chat_id = message.chat.id

    if not is_from_owner:
        logging.info(f"⚠️ .spam от не-владельца соединения — игнорируем")
        return

    if len(parts) < 3:
        await bot.send_message(chat_id=owner_id, text="❌ Формат: .spam <число> <текст>\nПример: .spam 10 привет")
        return
    try:
        count = int(parts[1])
    except ValueError:
        await bot.send_message(chat_id=owner_id, text="❌ Число должно быть целым.")
        return
    if count < 1 or count > SPAM_MAX:
        await bot.send_message(chat_id=owner_id, text=f"❌ Число от 1 до {SPAM_MAX}.")
        return

    spam_text = parts[2]
    try:
        await bot(DeleteBusinessMessages(business_connection_id=bc_id, message_ids=[message.message_id]))
        logging.info(f"🗑 Команда .spam удалена (msg {message.message_id})")
    except Exception as e:
        logging.error(f"delete_business_messages error: {type(e).__name__}: {e}")

    sent = 0
    for i in range(count):
        try:
            result = await bot.send_message(chat_id=chat_id, text=spam_text, business_connection_id=bc_id)
            try:
                save_message(result, bc_id, is_from_owner=True, fallback_user_id=owner_id, fallback_user_name="Вы")
            except Exception as se:
                logging.error(f"save sent msg error: {se}")
            sent += 1
        except Exception as e:
            logging.error(f"spam send error (i={i}): {e}")
            break
        await asyncio.sleep(SPAM_DELAY)
    logging.info(f"✅ .spam завершён: отправлено {sent}/{count}")

# --- КОМАНДА .ai ---
async def handle_ai_command(message: types.Message, bc_id: str, owner_id: int):
    text = (message.text or "").strip()
    prompt = text[3:].strip()
    if not prompt:
        await bot.send_message(chat_id=owner_id, text="❌ Использование: .ai <вопрос>")
        return
    try:
        await bot(DeleteBusinessMessages(business_connection_id=bc_id, message_ids=[message.message_id]))
    except Exception as e:
        logging.error(f"delete .ai command error: {e}")

    reply = await get_ai_reply(prompt)
    if not reply:
        await bot.send_message(chat_id=owner_id, text="❌ ИИ недоступен.")
        return
    try:
        result = await bot.send_message(chat_id=message.chat.id, text=reply, business_connection_id=bc_id)
        save_message(result, bc_id, is_from_owner=True, fallback_user_id=owner_id, fallback_user_name="Вы")
    except Exception as e:
        logging.error(f"send ai reply error: {e}")

# --- БОТ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("👋 Бот следит за удалёнными сообщениями.\n\nКоманды:\n.spam <число> <текст> — повторить сообщение N раз\n.ai <вопрос> — получить ответ от ИИ")

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
        if not business_owner_id:
            logging.warning("Не определили владельца — пропускаем")
            return

        author_id = message.from_user.id if message.from_user else 0
        is_from_owner = (author_id == business_owner_id)
        text = (message.text or "").strip()

        if text.lower().startswith(".spam"):
            if is_command_processed(message.chat.id, message.message_id): return
            mark_command_processed(message.chat.id, message.message_id)
            await handle_spam_command(message, bc_id, is_from_owner, business_owner_id)
            return

        if text.lower().startswith(".ai"):
            if is_command_processed(message.chat.id, message.message_id): return
            mark_command_processed(message.chat.id, message.message_id)
            await handle_ai_command(message, bc_id, business_owner_id)
            return

        save_message(message, bc_id, is_from_owner, fallback_user_id=business_owner_id, fallback_user_name="Вы")
        logging.info(f"💾 Сохранено msg {message.message_id}, автор: {'владелец' if is_from_owner else 'собеседник'}")

        if not is_from_owner and AI_ENABLED and text:
            logging.info(f"🤖 Запрос к ИИ для ответа: «{text[:60]}...»")
            reply = await get_ai_reply(text)
            if reply:
                try:
                    result = await bot.send_message(chat_id=message.chat.id, text=reply, business_connection_id=bc_id)
                    save_message(result, bc_id, is_from_owner=True, fallback_user_id=business_owner_id, fallback_user_name="ИИ")
                    logging.info(f"🤖 ИИ ответил: «{reply[:60]}...»")
                except Exception as e:
                    logging.error(f"send ai reply error: {e}")
    except Exception as e:
        logging.error(f"business_message error: {e}")

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
        save_message(message, bc_id, is_from_owner, fallback_user_id=business_owner_id or 0, fallback_user_name="Вы")
    except Exception as e:
        logging.error(f"Edit error: {e}")

async def send_copy(chat_id: int, header: str, text: str, content_type: str, file_id: str | None, caption: str):
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
    logging.info(f"🔔 deleted_business_messages: chat={event.chat.id}, bc={bc_id}, ids={event.message_ids}")

    business_owner_id = None
    if bc_id:
        try:
            conn_info = await bot.get_business_connection(bc_id)
            business_owner_id = conn_info.user.id
        except Exception as e:
            logging.error(f"get_business_connection error: {e}")

    if not business_owner_id:
        logging.error("Не удалось определить владельца — пропускаем")
        return

    for msg_id in event.message_ids:
        row = get_message(event.chat.id, msg_id)
        if not row:
            logging.warning(f"Msg {msg_id} не в БД")
            continue

        (chat_id, message_id, user_id, user_name, user_username, bc, is_from_owner, text, content_type, file_id, caption, date) = row
        header = build_header(user_name=user_name or "Неизвестный", user_username=user_username or "",
                              user_id=user_id, chat_id=chat_id, date_iso=date,
                              content_type=content_type, is_from_owner=bool(is_from_owner))
        try:
            await send_copy(chat_id=business_owner_id, header=header, text=text,
                            content_type=content_type, file_id=file_id, caption=caption)
            logging.info(f"✅ Отправлено {business_owner_id}")
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
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s [%(levelname)s] %(message)s")
    init_db()
    logging.info(f"🚀 Бот запущен. ИИ (DeepSeek): {'включён' if AI_ENABLED else 'выключен'}")

    asyncio.create_task(git_sync_loop())
    asyncio.create_task(periodic_cleanup())

    await dp.start_polling(bot, allowed_updates=["message", "edited_message", "callback_query",
                                                 "business_connection", "business_message",
                                                 "edited_business_message", "deleted_business_messages"],
                           drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
