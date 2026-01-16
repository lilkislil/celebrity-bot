import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

# Загрузка данных персоны
with open("persona.txt", "r", encoding="utf-8") as f:
    PERSONA = f.read()

# Настройка OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Настройка логов
logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я — ваш виртуальный собеседник. О чём поговорим?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
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
        logging.error(f"Ошибка: {e}")

def main():
    app = Application.builder().token(os.getenv("8446603587:AAHAm8-R0obNuVhGyl4EnaeCuxZDawkIfXM")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()