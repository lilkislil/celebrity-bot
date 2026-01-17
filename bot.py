import os
import logging
import hashlib
import time
from typing import Dict, Tuple, List
from datetime import datetime, timedelta
from collections import defaultdict

from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from groq import Groq

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ЗАГРУЗКА ПЕРСОНЫ ====================
try:
    with open("persona.txt", "r", encoding="utf-8") as f:
        PERSONA = f.read()
    logger.info("✅ Персона загружена из persona.txt")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки персонажа: {e}")
    PERSONA = "Ты - полезный AI ассистент."

# ==================== ИНИЦИАЛИЗАЦИЯ GROQ ====================
try:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY не задан в переменных окружения")
    client = Groq(api_key=groq_api_key)
    logger.info("✅ Groq клиент инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Groq: {e}")
    raise

# ==================== ИНИЦИАЛИЗАЦИЯ БОТА ====================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан")

PORT = int(os.getenv("PORT", 10000))
HOST = "0.0.0.0"
WEBHOOK_PATH = f"/webhook/{TOKEN}"
BASE_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'localhost')}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

# ==================== КЛАСС ОБРАБОТЧИКА СООБЩЕНИЙ ====================
class MessageHandler:
    def __init__(self):
        self.message_cache: Dict[str, Tuple[str, datetime]] = {}
        self.last_messages: Dict[str, Tuple[str, float]] = {}
        self.user_histories: Dict[str, List[dict]] = defaultdict(list)
        
        self.CACHE_TTL = 1800  # 30 минут
        self.DUPLICATE_TIMEOUT = 10  # 10 секунд
        self.MAX_HISTORY = 8  # 8 последних пар сообщений
    
    async def handle(self, message: types.Message):
        user_id = str(message.from_user.id)
        user_message = message.text.strip()
        current_time = time.time()
        
        # Игнорируем команды
        if user_message.startswith('/'):
            return
        
        # 1. Проверка на дублирование (быстрое повторение)
        if self._is_duplicate(user_id, user_message, current_time):
            await message.answer("Пожалуйста, не повторяйте сообщения так быстро.")
            return
        
        # 2. Проверка кэша (точный повтор)
        cached_reply = self._get_cached_reply(user_id, user_message)
        if cached_reply:
            await message.answer(cached_reply)
            logger.info(f"📦 Кэш: ответ для {user_id}")
            return
        
        # 3. Подготовка истории диалога
        if not self.user_histories[user_id]:
            self.user_histories[user_id].append({"role": "system", "content": PERSONA})
        
        conversation = self.user_histories[user_id].copy()
        conversation.append({"role": "user", "content": user_message})
        
        # 4. Генерация ответа
        try:
            logger.info(f"🧠 Генерация ответа для {user_id}: '{user_message[:50]}...'")
            start_time = time.time()
            
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=conversation,
                max_tokens=400,
                temperature=0.7,
                top_p=0.9
            )
            
            generation_time = time.time() - start_time
            reply = response.choices[0].message.content.strip()
            
            logger.info(f"✅ Ответ сгенерирован за {generation_time:.2f} сек, токенов: {response.usage.completion_tokens}")
            
            # 5. Обновление истории
            conversation.append({"role": "assistant", "content": reply})
            # Сохраняем только последние MAX_HISTORY пар сообщений
            self.user_histories[user_id] = conversation[-self.MAX_HISTORY*2:]  
            
            # 6. Кэширование ответа
            self._cache_reply(user_id, user_message, reply)
            
            # 7. Отправка ответа (разбиваем если длинный)
            await self._send_long_message(message, reply)
            logger.info(f"📤 Ответ отправлен пользователю {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка генерации: {e}")
            await message.answer("Произошла ошибка. Попробуйте позже.")
    
    async def _send_long_message(self, message: types.Message, text: str):
        """Отправляет длинные сообщения частями"""
        if len(text) <= 4096:  # Лимит Telegram
            await message.answer(text)
        else:
            # Разбиваем на части
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.answer(chunk)
                else:
                    await message.answer(chunk)
    
    def _is_duplicate(self, user_id: str, message: str, current_time: float) -> bool:
        """Проверяет, не повторяется ли сообщение слишком быстро"""
        if user_id in self.last_messages:
            last_msg, last_time = self.last_messages[user_id]
            if last_msg == message and (current_time - last_time) < self.DUPLICATE_TIMEOUT:
                logger.info(f"🔄 Дублирование сообщения от {user_id}")
                return True
        
        self.last_messages[user_id] = (message, current_time)
        return False
    
    def _get_cached_reply(self, user_id: str, message: str) -> str:
        """Получает ответ из кэша"""
        message_hash = hashlib.md5(message.encode()).hexdigest()
        cache_key = f"{user_id}:{message_hash}"
        
        if cache_key in self.message_cache:
            reply, timestamp = self.message_cache[cache_key]
            if datetime.now() - timestamp < timedelta(seconds=self.CACHE_TTL):
                return reply
        
        return ""
    
    def _cache_reply(self, user_id: str, message: str, reply: str):
        """Сохраняет ответ в кэш"""
        message_hash = hashlib.md5(message.encode()).hexdigest()
        cache_key = f"{user_id}:{message_hash}"
        self.message_cache[cache_key] = (reply, datetime.now())

# ==================== ИНИЦИАЛИЗАЦИЯ ОБРАБОТЧИКА ====================
message_handler = MessageHandler()

# ==================== TELEGRAM КОМАНДЫ ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Привет. Я — Ягами Лайт. Чем могу помочь?")

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
Доступные команды:
/start - Начать диалог
/help - Показать это сообщение
/clear - Очистить историю диалога
/stats - Показать статистику

Просто напишите сообщение, чтобы пообщаться.
"""
    await message.answer(help_text)

@router.message(Command("clear"))
async def cmd_clear(message: Message):
    user_id = str(message.from_user.id)
    if user_id in message_handler.user_histories:
        # Оставляем только системное сообщение
        message_handler.user_histories[user_id] = [
            {"role": "system", "content": PERSONA}
        ]
        await message.answer("История диалога очищена.")
    else:
        await message.answer("У вас нет активного диалога.")

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    user_id = str(message.from_user.id)
    stats_text = f"""
📊 Статистика:
Пользователь: {user_id}
История сообщений: {len(message_handler.user_histories.get(user_id, [])) - 1 if user_id in message_handler.user_histories else 0}
Кэшированных ответов: {len([k for k in message_handler.message_cache.keys() if k.startswith(f"{user_id}:")])}
"""
    await message.answer(stats_text)

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
@router.message()
async def handle_message(message: types.Message):
    await message_handler.handle(message)

# ==================== WEBHOOK НАСТРОЙКИ ====================
async def on_startup(app: web.Application):
    logger.info("🚀 Запуск бота...")
    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True
    )
    logger.info(f"🔗 Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    logger.info("🛑 Выключение бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()
    logger.info("✅ Бот выключен")

# ==================== ЗАПУСК ПРИЛОЖЕНИЯ ====================
def main():
    dp.include_router(router)

    app = web.Application()
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=TOKEN
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    logger.info(f"🌐 Запуск сервера на {HOST}:{PORT}")
    web.run_app(app, host=HOST, port=PORT)

if __name__ == "__main__":
    main()