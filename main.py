import asyncio
import logging
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession

# ================= НАСТРОЙКИ =================
# ОБЯЗАТЕЛЬНО СМЕНИТЕ ТОКЕН В @BotFather!
BOT_TOKEN = "8857613656:AAFugohLIVxAr5jnR3oD8QtXo0F70M-5Ri4"

# Если у вас VPN, можно оставить None. Если прокси - укажите "socks5://IP:PORT"
PROXY_URL = None # Например: "socks5://127.0.0.1:1080"

# Временная база данных (сбросится при перезапуске)
users_db = {}

# ================= ИНИЦИАЛИЗАЦИЯ =================
if PROXY_URL:
    session = AiohttpSession(proxy=PROXY_URL)
    bot = Bot(token=BOT_TOKEN, session=session)
else:
    bot = Bot(token=BOT_TOKEN)

dp = Dispatcher()

# Состояния для ввода своей суммы
class BalanceStates(StatesGroup):
    waiting_for_amount = State()

# ================= БАЗА ДАННЫХ (ЗАГЛУШКА) =================
def get_user(user_id, username, first_name):
    if user_id not in users_db:
        users_db[user_id] = {
            "balance": 0.00,
            "purchases": [],
            "spent": 0.00,
            "username": username,
            "first_name": first_name,
            "reg_date": datetime.now().strftime("%d.%m.%Y")
        }
    return users_db[user_id]

# ================= КЛАВИАТУРЫ =================

def main_menu_kb():
    """Постоянное меню снизу (Reply Keyboard)"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="🛍 Каталог")
    builder.button(text="👤 Профиль")
    builder.button(text="💵 Пополнить баланс")
    builder.button(text="🆘 Поддержка")
    builder.button(text="ℹ️ Информация")
    builder.adjust(2, 2, 1) # 2 кнопки, 2 кнопки, 1 кнопка
    return builder.as_markup(resize_keyboard=True)

def catalog_inline_kb():
    """Меню каталога"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🧠 API-ключи для нейросетей", callback_data="cat_ai")
    builder.button(text="🚀 Виртуальные серверы", callback_data="cat_vps")
    builder.button(text="🛡️ Антидетект-браузеры", callback_data="cat_antidetect")
    builder.button(text="🔑 Лицензионные ключи", callback_data="cat_licenses")
    builder.button(text="⬅️ Назад", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()

def ai_inline_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="OpenAI GPT-5 — 2800 ₽", callback_data="buy_gpt5")
    builder.button(text="Claude 4.1 Opus — 3100 ₽", callback_data="buy_claude")
    builder.button(text="Gemini Pro — 10400 ₽", callback_data="buy_gemini")
    builder.button(text="Mistral Medium 3 — 1780 ₽", callback_data="buy_mistral")
    builder.button(text="Midjourney v6 — 3400 ₽", callback_data="buy_midjourney")
    builder.button(text="DALL-E 3 — 2400 ₽", callback_data="buy_dalle")
    builder.button(text="Runway ML — 2700 ₽", callback_data="buy_runway")
    builder.button(text="⬅️ Назад к категориям", callback_data="back_to_catalog")
    builder.adjust(1)
    return builder.as_markup()

def vps_inline_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Базовый VPS (KVM) — 390 ₽", callback_data="buy_vps_base")
    builder.button(text="Продуктивный VPS (NVMe) — 690 ₽", callback_data="buy_vps_pro")
    builder.button(text="Windows VPS (RDP) — 990 ₽", callback_data="buy_vps_win")
    builder.button(text="Игровой сервер — 1290 ₽", callback_data="buy_game")
    builder.button(text="Сервер для стриминга — 3490 ₽", callback_data="buy_stream")
    builder.button(text="Хранилище данных — 890 ₽", callback_data="buy_storage")
    builder.button(text="Хостинг для ботов — 490 ₽", callback_data="buy_bots")
    builder.button(text="Выделенные прокси — 190 ₽", callback_data="buy_proxy")
    builder.button(text="⬅️ Назад к категориям", callback_data="back_to_catalog")
    builder.adjust(1)
    return builder.as_markup()

def antidetect_inline_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="AdsPower Pro — 8900 ₽", callback_data="buy_adspower")
    builder.button(text="Dolphinfanty Lifetime — 12900 ₽", callback_data="buy_dolphin")
    builder.button(text="Multilogin X — 16500 ₽", callback_data="buy_multilogin")
    builder.button(text="GoLogin Business — 9900 ₽", callback_data="buy_gologin")
    builder.button(text="Kameleo Premium — 11900 ₽", callback_data="buy_kameleo")
    builder.button(text="VMLogin Business — 9500 ₽", callback_data="buy_vmlogin")
    builder.button(text="Готовые профили — 290 ₽", callback_data="buy_profiles")
    builder.button(text="VPS + Антидетект связка — 1590 ₽", callback_data="buy_bundle")
    builder.button(text="⬅️ Назад к категориям", callback_data="back_to_catalog")
    builder.adjust(1)
    return builder.as_markup()

def licenses_inline_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Microsoft Windows 11 Pro (Retail) — 2900 ₽", callback_data="buy_win11")
    builder.button(text="Microsoft Office 2021 Pro Plus — 4500 ₽", callback_data="buy_office")
    builder.button(text="Adobe Creative Cloud (год) — 18900 ₽", callback_data="buy_adobe")
    builder.button(text="ESET NOD32 Antivirus (2 года) — 3200 ₽", callback_data="buy_eset")
    builder.button(text="Kaspersky Internet Security (1 год) — 1800 ₽", callback_data="buy_kaspersky")
    builder.button(text="Steam (подарочные карты 2000 ₽) — 1900 ₽", callback_data="buy_steam")
    builder.button(text="Norton 360 Deluxe (1 год) — 3500 ₽", callback_data="buy_norton")
    builder.button(text="Corel Draw Graphics Suite 2024 — 55000 ₽", callback_data="buy_corel")
    builder.button(text="WinRAR (бессрочная) — 1200 ₽", callback_data="buy_winrar")
    builder.button(text="YouTube Premium (1 год) — 6500 ₽", callback_data="buy_youtube")
    builder.button(text="⬅️ Назад к категориям", callback_data="back_to_catalog")
    builder.adjust(1)
    return builder.as_markup()

def balance_inline_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 1 000 ₽", callback_data="topup_1000")
    builder.button(text="💰 2 000 ₽", callback_data="topup_2000")
    builder.button(text="💰 3 000 ₽", callback_data="topup_3000")
    builder.button(text="💰 5 000 ₽", callback_data="topup_5000")
    builder.button(text="💰 10 000 ₽", callback_data="topup_10000")
    builder.button(text="💰 20 000 ₽", callback_data="topup_20000")
    builder.button(text="✏️ Своя сумма", callback_data="topup_custom")
    builder.button(text="❌ Отмена", callback_data="back_to_start")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()

def profile_inline_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Мои покупки", callback_data="my_purchases")
    builder.button(text="🧾 История пополнений", callback_data="topup_history")
    builder.button(text="🔄 Обновить", callback_data="refresh_profile")
    builder.adjust(1)
    return builder.as_markup()

# ================= ОБРАБОТЧИКИ =================

@dp.message(CommandStart())
async def command_start(message: types.Message):
    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    text = (
        f"👋 Добро пожаловать в наш магазин, {user['first_name']}!\n\n"
        f"📋 Мы предлагаем:\n"
        f"• 🧠 API-ключи для нейросетей\n"
        f"• 🚀 Виртуальные серверы (VPS/VDS)\n"
        f"• 🛡️ Антидетект-браузеры\n\n"
        f"💰 Ваш текущий баланс: {user['balance']:.2f} ₽\n\n"
        f"_Выберите нужный раздел в меню ниже_ 👇"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="Markdown")

@dp.message(F.text == "🛍 Каталог")
async def show_catalog(message: types.Message):
    text = "🛍 **КАТАЛОГ ТОВАРОВ**\n\nВыберите категорию:"
    await message.answer(text, reply_markup=catalog_inline_kb(), parse_mode="Markdown")

@dp.message(F.text == "💵 Пополнить баланс")
async def show_balance(message: types.Message):
    text = (
        "💵 **ПОПОЛНЕНИЕ БАЛАНСА**\n\n"
        "💳 Минимальная сумма: 1000 ₽\n\n"
        "Выберите сумму или введите свою:"
    )
    await message.answer(text, reply_markup=balance_inline_kb(), parse_mode="Markdown")

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    username = f"@{user['username']}" if user['username'] else "нет"
    text = (
        "👤 **МОЙ ПРОФИЛЬ**\n\n"
        "📋 **Личная информация:**\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"👤 Имя: {user['first_name']}\n"
        f"✏️ Username: {username}\n"
        f"📅 Регистрация: {user['reg_date']}\n\n"
        "💰 **Финансовая информация:**\n"
        f"💵 Основной баланс: {user['balance']:.2f} ₽\n\n"
        "🛍 **Статистика покупок:**\n"
        f"📦 Всего заказов: {len(user['purchases'])}\n"
        f"💸 Потрачено: {user['spent']:.2f} ₽"
    )
    await message.answer(text, reply_markup=profile_inline_kb(), parse_mode="Markdown")

@dp.message(F.text == "🆘 Поддержка")
async def show_support(message: types.Message):
    text = (
        "🆘 **ПОДДЕРЖКА**\n\n"
        "По всем вопросам пишите нашему саппорту\n\n"
        "График работы: 10:00-22:00 мск\n\n"
        "👨‍💻 Связаться: @admin_username"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "ℹ️ Информация")
async def show_info(message: types.Message):
    await message.answer("ℹ️ Это тестовый бот-магазин. Все данные временные.", reply_markup=main_menu_kb())

# --- CALLBACKS: КАТАЛОГ ---

@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data == "back_to_catalog")
async def back_to_catalog(callback: types.CallbackQuery):
    text = "🛍 **КАТАЛОГ ТОВАРОВ**\n\nВыберите категорию:"
    await callback.message.edit_text(text, reply_markup=catalog_inline_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "cat_ai")
async def cat_ai(callback: types.CallbackQuery):
    text = (
        "🧠 **API-КЛЮЧИ ДЛЯ НЕЙРОСЕТЕЙ**\n\n"
        "Доступ к самым мощным нейросетям мира\n\n"
        "**Выберите товар:**"
    )
    await callback.message.edit_text(text, reply_markup=ai_inline_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "cat_vps")
async def cat_vps(callback: types.CallbackQuery):
    text = (
        "🚀 **ВИРТУАЛЬНЫЕ СЕРВЕРЫ**\n\n"
        "VPS/VDS для любых задач\n\n"
        "**Выберите товар:**"
    )
    await callback.message.edit_text(text, reply_markup=vps_inline_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "cat_antidetect")
async def cat_antidetect(callback: types.CallbackQuery):
    text = (
        "🛡️ **АНТИДЕТЕКТ-БРАУЗЕРЫ**\n\n"
        "Профессиональные инструменты для мультиаккаунтинга\n\n"
        "**Выберите товар:**"
    )
    await callback.message.edit_text(text, reply_markup=antidetect_inline_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "cat_licenses")
async def cat_licenses(callback: types.CallbackQuery):
    text = (
        "🔑 **ЛИЦЕНЗИОННЫЕ КЛЮЧИ**\n\n"
        "Официальное ПО и сервисы по выгодным ценам\n\n"
        "**Выберите товар:**"
    )
    await callback.message.edit_text(text, reply_markup=licenses_inline_kb(), parse_mode="Markdown")
    await callback.answer()

# --- CALLBACKS: ПОКУПКА ---

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    item_code = callback.data.replace("buy_", "")
    
    # Словарь цен для проверки (можно вынести в БД)
    prices = {
        "gpt5": 2800, "claude": 3100, "gemini": 10400, "mistral": 1780,
        "midjourney": 3400, "dalle": 2400, "runway": 2700,
        "vps_base": 390, "vps_pro": 690, "vps_win": 990, "game": 1290,
        "stream": 3490, "storage": 890, "bots": 490, "proxy": 190,
        "adspower": 8900, "dolphin": 12900, "multilogin": 16500, "gologin": 9900,
        "kameleo": 11900, "vmlogin": 9500, "profiles": 290, "bundle": 1590,
        "win11": 2900, "office": 4500, "adobe": 18900, "eset": 3200,
        "kaspersky": 1800, "steam": 1900, "norton": 3500, "corel": 55000,
        "winrar": 1200, "youtube": 6500
    }
    
    price = prices.get(item_code, 0)
    user = get_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    
    if user["balance"] < price:
        await callback.answer("❌ Недостаточно средств! Пополните баланс.", show_alert=True)
        return

    # Списание баланса
    user["balance"] -= price
    user["spent"] += price
    user["purchases"].append({"item": item_code, "price": price, "date": datetime.now().strftime("%d.%m.%Y %H:%M")})
    
    await callback.message.answer(
        f"✅ **Успешная покупка!**\n\n"
        f"Товар: `{item_code}`\n"
        f"Списано: {price} ₽\n"
        f"Остаток: {user['balance']:.2f} ₽\n\n"
        f"Ссылка на товар/ключ: `https://example.com/key`"
    )
    await callback.answer("Товар куплен!")

# --- CALLBACKS: ПОПОЛНЕНИЕ ---

@dp.callback_query(F.data.startswith("topup_"))
async def process_topup(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "topup_custom":
        await state.set_state(BalanceStates.waiting_for_amount)
        await callback.message.answer("✏️ Введите сумму пополнения (целое число):")
        await callback.answer()
        return

    amount = int(callback.data.replace("topup_", ""))
    user = get_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    user["balance"] += amount
    
    await callback.message.answer(f"✅ Баланс успешно пополнен на {amount} ₽!\nТекущий баланс: {user['balance']:.2f} ₽")
    await callback.answer("Баланс пополнен!")

@dp.message(BalanceStates.waiting_for_amount)
async def process_custom_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount < 1000:
            await message.answer("❌ Минимальная сумма пополнения 1000 ₽. Попробуйте снова:")
            return
        
        user = get_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        user["balance"] += amount
        await state.clear()
        await message.answer(f"✅ Баланс успешно пополнен на {amount} ₽!\nТекущий баланс: {user['balance']:.2f} ₽", reply_markup=main_menu_kb())
    except ValueError:
        await message.answer("❌ Пожалуйста, введите целое число:")

# --- CALLBACKS: ПРОФИЛЬ ---

@dp.callback_query(F.data == "refresh_profile")
async def refresh_profile(callback: types.CallbackQuery):
    # Просто перезапускаем профиль
    await callback.message.delete()
    await show_profile(callback.message)
    await callback.answer("Обновлено!")

@dp.callback_query(F.data == "my_purchases")
async def my_purchases(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    if not user["purchases"]:
        await callback.answer("У вас пока нет покупок.", show_alert=True)
        return
    
    text = "📦 **МОИ ПОКУПКИ**\n\n"
    for p in user["purchases"]:
        text += f"• {p['item']} — {p['price']} ₽ ({p['date']})\n"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "topup_history")
async def topup_history(callback: types.CallbackQuery):
    await callback.answer("История пополнений пуста (тестовый режим).", show_alert=True)

# ================= ЗАПУСК =================
async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print("Бот запущен...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
