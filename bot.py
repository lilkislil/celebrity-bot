import os
import logging
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from groq import Groq

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    with open("persona.txt", "r", encoding="utf-8") as f:
        PERSONA = f.read()
    logger.info("✅ persona.txt")
except Exception as e:
    logger.error(f"❌ persona.txt: {e}")
    raise

try:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY не задан в переменных окружения")
    client = Groq(api_key=groq_api_key)
    logger.info("✅ Groq клиент создан")
except Exception as e:
    logger.error(f"❌ Ошибка Groq: {e}")
    raise

# Инициализация
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан")

PORT = int(os.getenv("PORT", 10000))
HOST = "0.0.0.0"
WEBHOOK_PATH = f"/{TOKEN}"
BASE_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'localhost')}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Привет, меня зовут Ягами Лайт.")

@router.message()
async def handle_message(message: types.Message):
    user_message = message.text
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": PERSONA},
                {"role": "user", "content": user_message}
            ],
            max_tokens=164,
            temperature=0.8
        )
        reply = response.choices[0].message.content.strip()
        await message.answer(reply)
    except Exception as e:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        logger.error(f"Ошибка генерации: {e}")

async def on_startup(app: web.Application):
    await bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"🔗 Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()

def main():
    dp.include_router(router)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host=HOST, port=PORT)

if __name__ == "__main__":
    main()
