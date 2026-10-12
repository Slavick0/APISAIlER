import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Ваш токен (ОБЯЗАТЕЛЬНО СМЕНИТЕ ЕГО ПОСЛЕ ТЕСТА!)
BOT_TOKEN = "8857613656:AAFugohLIVxAr5jnR3oD8QtXo0F70M-5Ri4"

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ ДЛЯ СОЗДАНИЯ КЛАВИАТУР ---

def get_main_menu():
    """Главное меню (Каталог товаров)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🧠 API-ключи для нейросетей", callback_data="category_ai")
    builder.button(text="🚀 Виртуальные серверы", callback_data="category_vps")
    builder.button(text="🛡️ Антидетект-браузеры", callback_data="category_antidetect")
    builder.button(text="🔑 Лицензионные ключи", callback_data="category_licenses")
    builder.adjust(1) # Расположить кнопки по одной в ряд
    return builder.as_markup()

def get_ai_menu():
    """Меню API-ключей для нейросетей"""
    builder = InlineKeyboardBuilder()
    # Примеры нейросетей
    builder.button(text="OpenAI GPT-4o — 2500 ₽", callback_data="buy_gpt4o")
    builder.button(text="Anthropic Claude 3 Opus — 2900 ₽", callback_data="buy_claude")
    builder.button(text="Google Gemini 1.5 Pro — 3200 ₽", callback_data="buy_gemini")
    builder.button(text="Midjourney v6 — 3400 ₽", callback_data="buy_midjourney")
    builder.button(text="Stable Diffusion 3 — 1500 ₽", callback_data="buy_sd3")
    builder.button(text="DALL-E 3 — 2400 ₽", callback_data="buy_dalle")
    builder.button(text="Mistral Large 2 — 1800 ₽", callback_data="buy_mistral")
    builder.button(text="Runway Gen-2 — 2700 ₽", callback_data="buy_runway")
    builder.button(text="⬅️ Назад к категориям", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

# --- ОБРАБОТЧИКИ КОМАНД И КНОПОК ---

@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    """Обработчик команды /start"""
    text = (
        "🛍 **КАТАЛОГ ТОВАРОВ**\n\n"
        "Выберите категорию:"
    )
    await message.answer(text, reply_markup=get_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    text = (
        "🛍 **КАТАЛОГ ТОВАРОВ**\n\n"
        "Выберите категорию:"
    )
    await callback.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "category_ai")
async def category_ai(callback: types.CallbackQuery):
    """Меню API-ключей"""
    text = (
        "🧠 **API-КЛЮЧИ ДЛЯ НЕЙРОСЕТЕЙ**\n\n"
        "Доступ к самым мощным нейросетям мира\n\n"
        "**Выберите товар:**"
    )
    await callback.message.edit_text(text, reply_markup=get_ai_menu(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    """Обработчик нажатия на конкретный товар"""
    item = callback.data.split("_")[1]
    
    # Здесь можно добавить логику отправки ссылки на оплату или выдачи ключа
    await callback.message.answer(f"Вы выбрали покупку: {item}.\n\nДля оплаты свяжитесь с администратором: @admin_username")
    await callback.answer("Товар выбран!")

# --- ЗАПУСК БОТА ---

async def main() -> None:
    # Включаем логирование
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    # Запускаем polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
