import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# 🔑 Токен прямо в коде
TOKEN = "8727943556:AAEKDsKwOYu3KLnXQUEW_b2a0FkaQsMLlhI"


bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("Привет!")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
