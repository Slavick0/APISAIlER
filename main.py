import asyncio
import logging
import sys
import sqlite3
import os
import re
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.methods import DeleteBusinessMessages

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

BOT_TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в Secrets!")
if not GIGACHAT_CREDENTIALS:
    raise ValueError("GIGACHAT_CREDENTIALS не задан в Secrets!")

AI_ENABLED = True
AI_MODEL = "GigaChat-2"
AI_HISTORY_LIMIT = 50

AI_SYSTEM_PROMPT = (
    "Ты — живой человек, ведёшь личную переписку в Telegram. "
    "НИКОГДА не упоминай, что ты ИИ, бот, программа, ассистент, модель или GigaChat. "
    "НИКОГДА не говори фраз вроде «я не могу», «я генеративная модель», «как ИИ», "
    "«я всего лишь программа», «я не имею чувств». "
    "Если тебя спрашивают «как дела», «как ты», «что делаешь» — отвечай как обычный человек: "
    "коротко, живо, с эмпатией. Например: «норм, сам как?», «да всё ок, ты как?», «отдыхаю, а ты?». "
    "Отвечай на русском, коротко (1-2 предложения), в дружеском стиле. "
    "Не перечисляй, не структурируй, не пиши списками. "
    "Если не знаешь ответ — уклоняйся по-человечески, не признавайся, что ты ИИ."
)

CERT_PATH = os.path.join(os.getcwd(), "russian_trusted_root_ca_pem.crt")

giga_client = GigaChat(
    credentials=GIGACHAT_CREDENTIALS,
    scope="GIGACHAT_API_PERS",
    model=AI_MODEL,
    verify_ssl_certs=False,
    ca_bundle_file=CERT_PATH if os.path.exists(CERT_PATH) else None
)

DB_PATH = "messages.db"
SPAM_MAX = 20
SPAM_DELAY = 0.7


# ==================== БАЗА ДАННЫХ ====================

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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_commands (
            chat_id INTEGER,
            message_id INTEGER,
            processed_at TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history_settings (
            chat_id INTEGER PRIMARY KEY,
            reset_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_mode (
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            started_at TEXT
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
    cursor.execute(
        "INSERT OR REPLACE INTO processed_commands (chat_id, message_id, processed_at) VALUES (?, ?, ?)",
        (chat_id, message_id, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def set_history_reset(chat_id: int, reset_at: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO history_settings (chat_id, reset_at) VALUES (?, ?)",
        (chat_id, reset_at)
    )
    conn.commit()
    conn.close()


def get_history_reset(chat_id: int) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT reset_at FROM history_settings WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def set_ai_mode(chat_id: int, enabled: bool):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if enabled:
        cursor.execute(
            "INSERT OR REPLACE INTO ai_mode (chat_id, enabled, started_at) VALUES (?, 1, ?)",
            (chat_id, datetime.now().isoformat())
        )
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO ai_mode (chat_id, enabled, started_at) VALUES (?, 0, NULL)",
            (chat_id,)
        )
    conn.commit()
    conn.close()


def is_ai_mode_on(chat_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT enabled FROM ai_mode WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and row[0])


def get_chat_history(chat_id: int, limit: int = 50) -> list:
    reset_at = get_history_reset(chat_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if reset_at:
        cursor.execute("""
            SELECT is_from_owner, text FROM messages
            WHERE chat_id = ? AND date > ? AND content_type = 'text' AND text != ''
            ORDER BY date ASC LIMIT ?
        """, (chat_id, reset_at, limit))
    else:
        cursor.execute("""
            SELECT is_from_owner, text FROM messages
            WHERE chat_id = ? AND content_type = 'text' AND text != ''
            ORDER BY date ASC LIMIT ?
        """, (chat_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows


def save_message(message: types.Message, business_connection_id: str, is_from_owner: bool,
                 fallback_user_id: int = 0, fallback_user_name: str = "Бот",
                 fallback_user_username: str = ""):
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
        (chat_id, message_id, user_id, user_name, user_username,
         business_connection_id, is_from_owner,
         text, content_type, file_id, caption, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (message.chat.id, message.message_id, user_id, user_name, user_username,
          business_connection_id or "", 1 if is_from_owner else 0,
          message.text or "", message.content_type, file_id, message.caption or "",
          message.date.isoformat() if message.date else datetime.now().isoformat()))
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
    cursor.execute("DELETE FROM processed_commands WHERE processed_at < datetime('now', ?)", (f'-{days} days',))
    conn.commit()
    conn.close()
    logging.info(f"🧹 Очистка: удалено {deleted} старых записей")


# ==================== GIT ====================

async def git_sync_loop():
    while True:
        await asyncio.sleep(60)
        try:
            subprocess.run(["git", "config", "user.email", "bot@example.com"], check=True)
            subprocess.run(["git", "config", "user.name", "Bot"], check=True)
            subprocess.run(["git", "add", DB_PATH], check=True)
            result = subprocess.run(["git", "commit", "-m", f"Update DB {datetime.now().isoformat()}"],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                subprocess.run(["git", "push"], check=True)
                logging.info("📤 БД синхронизирована с GitHub")
        except Exception as e:
            logging.error(f"Git sync error: {e}")


# ==================== УТИЛИТЫ ====================

def format_time(iso_date: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime("%d.%m.%Y | %H:%M:%S")
    except Exception:
        return iso_date


def get_type_label(content_type: str) -> str:
    labels = {"text": "текстовое сообщение", "photo": "фото", "video": "видео",
              "document": "документ", "voice": "голосовое сообщение", "audio": "аудио",
              "sticker": "стикер", "video_note": "видеосообщение", "animation": "GIF"}
    return labels.get(content_type, content_type)


def build_header(user_name, user_username, user_id, chat_id, date_iso, content_type, is_from_owner):
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


def parse_date_time(date_str: str, time_str: str):
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
        return dt.isoformat()
    except Exception:
        return None


# ==================== GIGACHAT ====================

async def get_ai_reply(chat_id: int, user_text: str) -> str | None:
    if not AI_ENABLED or not giga_client:
        return None
    try:
        history = get_chat_history(chat_id, limit=AI_HISTORY_LIMIT)
        messages = [Messages(role=MessagesRole.SYSTEM, content=AI_SYSTEM_PROMPT)]
        for is_from_owner, text in history:
            if not text:
                continue
            role = MessagesRole.ASSISTANT if is_from_owner else MessagesRole.USER
            messages.append(Messages(role=role, content=text))
        if not history or history[-1][1] != user_text:
            messages.append(Messages(role=MessagesRole.USER, content=user_text))

        logging.info(f"🧠 GigaChat: {len(messages)} сообщений в контексте")
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: giga_client.chat(Chat(messages=messages)))
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"GigaChat API error: {type(e).__name__}: {e}")
        return None


# ==================== КОМАНДА .spam ====================

async def handle_spam_command(message, bc_id, is_from_owner, owner_id):
    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    chat_id = message.chat.id
    if not is_from_owner:
        return
    if len(parts) < 3:
        await bot.send_message(chat_id=owner_id, text="❌ Формат: .spam <число> <текст>")
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
    except Exception as e:
        logging.error(f"delete spam cmd error: {e}")

    sent = 0
    for i in range(count):
        try:
            result = await bot.send_message(chat_id=chat_id, text=spam_text, business_connection_id=bc_id)
            save_message(result, bc_id, is_from_owner=True, fallback_user_id=owner_id, fallback_user_name="Вы")
            sent += 1
        except Exception as e:
            logging.error(f"spam send error (i={i}): {e}")
            break
        await asyncio.sleep(SPAM_DELAY)
    logging.info(f"✅ .spam: отправлено {sent}/{count}")


# ==================== КОМАНДА .forget ====================

async def handle_forget_command(message, bc_id: str, owner_id: int):
    chat_id = message.chat.id
    set_history_reset(chat_id, datetime.now().isoformat())
    try:
        await bot(DeleteBusinessMessages(business_connection_id=bc_id, message_ids=[message.message_id]))
    except Exception as e:
        logging.error(f"delete forget cmd error: {e}")
    logging.info(f"🧹 История сброшена для чата {chat_id}")
    try:
        await bot.send_message(chat_id=chat_id, text="Хорошо, начнём с чистого листа.",
                               business_connection_id=bc_id)
    except Exception as e:
        logging.error(f"forget reply error: {e}")


# ==================== КОМАНДА .ai ====================

async def handle_ai_command(message, bc_id: str, owner_id: int):
    text = (message.text or "").strip()
    chat_id = message.chat.id

    # .ai off
    if re.match(r"^\.ai\s+off$", text, re.IGNORECASE):
        set_ai_mode(chat_id, False)
        try:
            await bot(DeleteBusinessMessages(business_connection_id=bc_id, message_ids=[message.message_id]))
        except Exception as e:
            logging.error(f"delete ai off error: {e}")
        logging.info(f"⏹ AI-режим выключен для чата {chat_id}")
        try:
            await bot.send_message(chat_id=chat_id, text="Хорошо, дальше отвечаешь ты.",
                                   business_connection_id=bc_id)
        except Exception as e:
            logging.error(f"ai off reply error: {e}")
        return

    # .ai on <дата> <время>
    m = re.match(r"^\.ai\s+on\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})$", text, re.IGNORECASE)
    if m:
        date_str, time_str = m.group(1), m.group(2)
        iso = parse_date_time(date_str, time_str)
        if not iso:
            await bot.send_message(chat_id=owner_id, text="❌ Не смог разобрать дату. Формат: `.ai on 14.10.2026 21:00`")
            return

        set_history_reset(chat_id, iso)
        set_ai_mode(chat_id, True)

        try:
            await bot(DeleteBusinessMessages(business_connection_id=bc_id, message_ids=[message.message_id]))
        except Exception as e:
            logging.error(f"delete ai on cmd error: {e}")

        logging.info(f"▶️ AI-режим ВКЛючён для чата {chat_id}, история с {iso}")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="Ок, я на связи. Пиши.",
                business_connection_id=bc_id
            )
        except Exception as e:
            logging.error(f"ai on reply error: {e}")
        return

    # .ai <вопрос> — разовый запрос
    prompt = text[3:].strip()
    if not prompt:
        await bot.send_message(chat_id=owner_id,
                               text="❌ Использование:\n`.ai <вопрос>`\n`.ai on 14.10.2026 21:00`\n`.ai off`")
        return

    try:
        await bot(DeleteBusinessMessages(business_connection_id=bc_id, message_ids=[message.message_id]))
    except Exception as e:
        logging.error(f"delete .ai cmd error: {e}")

    reply = await get_ai_reply(chat_id, prompt)
    if not reply:
        await bot.send_message(chat_id=owner_id, text="❌ ИИ недоступен.")
        return
    try:
        result = await bot.send_message(chat_id=chat_id, text=reply, business_connection_id=bc_id)
        save_message(result, bc_id, is_from_owner=True, fallback_user_id=owner_id, fallback_user_name="Вы")
    except Exception as e:
        logging.error(f"send ai reply error: {e}")


# ==================== БОТ ====================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Бот следит за удалёнными сообщениями.\n\n"
        "Команды:\n"
        "`.spam <число> <текст>` — повторить N раз\n"
        "`.ai <вопрос>` — разовый ответ ИИ\n"
        "`.ai on 14.10.2026 21:00` — включить ИИ-диалог с этой даты\n"
        "`.ai off` — выключить ИИ-диалог\n"
        "`.forget` — сбросить историю"
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
        if not business_owner_id:
            return

        author_id = message.from_user.id if message.from_user else 0
        is_from_owner = (author_id == business_owner_id)
        text = (message.text or "").strip()
        chat_id = message.chat.id

        # --- Команды ---
        if text.lower().startswith(".forget") or text.lower() == "забудь историю":
            if is_command_processed(chat_id, message.message_id): return
            mark_command_processed(chat_id, message.message_id)
            await handle_forget_command(message, bc_id, business_owner_id)
            return

        if text.lower().startswith(".spam"):
            if is_command_processed(chat_id, message.message_id): return
            mark_command_processed(chat_id, message.message_id)
            await handle_spam_command(message, bc_id, is_from_owner, business_owner_id)
            return

        if text.lower().startswith(".ai"):
            if is_command_processed(chat_id, message.message_id): return
            mark_command_processed(chat_id, message.message_id)
            await handle_ai_command(message, bc_id, business_owner_id)
            return

        # --- Обычное сообщение ---
        save_message(message, bc_id, is_from_owner,
                     fallback_user_id=business_owner_id,
                     fallback_user_name="Вы")
        logging.info(f"💾 Сохранено msg {message.message_id}, автор: {'владелец' if is_from_owner else 'собеседник'}")

        # --- AI-режим: отвечаем на сообщения СОБЕСЕДНИКА, пока не выключен ---
        ai_on = is_ai_mode_on(chat_id)

        if ai_on and not is_from_owner and AI_ENABLED and text:
            logging.info(f"🤖 AI-режим: отвечаю собеседнику «{text[:60]}...»")
            reply = await get_ai_reply(chat_id, text)
            if reply:
                try:
                    result = await bot.send_message(chat_id=chat_id, text=reply, business_connection_id=bc_id)
                    save_message(result, bc_id, is_from_owner=True,
                                 fallback_user_id=business_owner_id, fallback_user_name="ИИ")
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
        save_message(message, bc_id, is_from_owner,
                     fallback_user_id=business_owner_id or 0,
                     fallback_user_name="Вы")
    except Exception as e:
        logging.error(f"Edit error: {e}")


async def send_copy(chat_id, header, text, content_type, file_id, caption):
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
    logging.info(f"🔔 deleted_business_messages: chat={event.chat.id}, ids={event.message_ids}")
    business_owner_id = None
    if bc_id:
        try:
            conn_info = await bot.get_business_connection(bc_id)
            business_owner_id = conn_info.user.id
        except Exception as e:
            logging.error(f"get_business_connection error: {e}")
    if not business_owner_id:
        return
    for msg_id in event.message_ids:
        row = get_message(event.chat.id, msg_id)
        if not row:
            logging.warning(f"Msg {msg_id} не в БД")
            continue
        (chat_id, message_id, user_id, user_name, user_username,
         bc, is_from_owner, text, content_type, file_id, caption, date) = row
        header = build_header(user_name, user_username, user_id, chat_id,
                              date, content_type, bool(is_from_owner))
        try:
            await send_copy(business_owner_id, header, text, content_type, file_id, caption)
            logging.info(f"✅ Удалённое отправлено {business_owner_id}")
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
    logging.info(f"🚀 Бот запущен. ИИ (GigaChat): {'включён' if AI_ENABLED else 'выключен'}")

    asyncio.create_task(git_sync_loop())
    asyncio.create_task(periodic_cleanup())

    await dp.start_polling(
        bot,
        allowed_updates=["message", "edited_message", "callback_query",
                         "business_connection", "business_message",
                         "edited_business_message", "deleted_business_messages"],
        drop_pending_updates=True
    )


if __name__ == "__main__":
    asyncio.run(main())
