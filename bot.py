import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    with open("persona.txt", "r", encoding="utf-8") as f:
        PERSONA = f.read()
    logger.info("✅ persona.txt успешно загружен")
except Exception as e:
    logger.error(f"❌ Ошибка при загрузке persona.txt: {e}")
    raise

try:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    logger.info("✅ Groq клиент создан")
except Exception as e:
    logger.error(f"❌ Ошибка Groq: {e}")
    raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я — ваш виртуальный собеседник. О чём поговорим?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    try:
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": PERSONA},
                {"role": "user", "content": user_message}
            ],
            max_tokens=150,
            temperature=0.8
        )
        reply = response.choices[0].message.content.strip()
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
        logger.error(f"Ошибка генерации: {e}")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN не задан!")
        return

    port = int(os.environ.get("PORT", 10000))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    webhook_url = f"https://{hostname}/{token}" if hostname != "localhost" else None

    logger.info(f"🚀 Запуск бота на порту {port}")
    if webhook_url:
        logger.info(f"🔗 Webhook URL: {webhook_url}")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=webhook_url
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()
