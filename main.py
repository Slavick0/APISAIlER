from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# 🔑 Токен прямо в коде
TOKEN = "8727943556:AAEKDsKwOYu3KLnXQUEW_b2a0FkaQsMLlhI"

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("Привет!")

@app.post("/api/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = types.Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return Response(status_code=200)

@app.get("/")
async def root():
    return {"status": "ok"}