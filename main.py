import asyncio
import logging
import time
import hmac
import hashlib
import binascii
import json
import os
import sys
from datetime import datetime
from contextlib import suppress

import aiohttp
import cloudscraper
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.client.bot import DefaultBotProperties

from dotenv import load_dotenv

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Загрузка переменных окружения ---
load_dotenv()
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Например: https://your-domain.com/webhook

# --- Конфигурация ---
BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
MIN_SELL_AMOUNT = 0.00000001

# --- Инициализация бота ---
bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- Инициализация HTTP клиента ---
class SafeTradeClient:
    def __init__(self):
        self.session = None
        self.scraper = None
    
    async def init(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    'Content-Type': 'application/json;charset=utf-8',
                    'Accept': 'application/json',
                    'User-Agent': 'SafeTrade-Client/1.0',
                    'Origin': 'https://safe.trade',
                    'Referer': 'https://safe.trade/'
                }
            )
        
        if self.scraper is None:
            self.scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                delay=10
            )
    
    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    def generate_signature(self, nonce: str, secret: str, key: str) -> str:
        hash_obj = hmac.new(secret.encode(), digestmod=hashlib.sha256)
        hash_obj.update((nonce + key).encode())
        signature = hash_obj.digest()
        return binascii.hexlify(signature).decode()
    
    def get_auth_headers(self) -> dict:
        nonce = str(int(time.time() * 1000))
        if not API_KEY or not API_SECRET:
            raise ValueError("API Key или API Secret не установлены.")
        
        signature = self.generate_signature(nonce, API_SECRET, API_KEY)
        
        return {
            "X-Auth-Apikey": API_KEY,
            "X-Auth-Nonce": nonce,
            "X-Auth-Signature": signature,
            "Content-Type": "application/json;charset=utf-8"
        }
    
    async def get_balances(self) -> str:
        await self.init()
        url = f"{BASE_URL}/trade/account/balances"
        
        try:
            headers = self.get_auth_headers()
            async with self.session.get(url, headers=headers) as response:
                logger.info(f"📡 Ответ от балансов: статус {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Успешный ответ: {data}")
                    
                    if isinstance(data, list):
                        non_zero_balances = [
                            f"{b.get('currency', '').upper()}: <code>{b.get('balance', '0')}</code>"
                            for b in data if float(b.get('balance', 0)) > 0
                        ]
                        
                        if non_zero_balances:
                            return "Ваши ненулевые балансы на SafeTrade:\n\n" + "\n".join(non_zero_balances)
                        else:
                            return "У вас нет ненулевых балансов на SafeTrade."
                    else:
                        return f"Ошибка: получен неожиданный формат данных: {data}"
                else:
                    error_text = await response.text()
                    return f"❌ Ошибка API: статус {response.status} - {error_text[:200]}"
                    
        except Exception as e:
            logger.error(f"❌ Ошибка при получении балансов: {e}")
            return f"❌ Ошибка при получении балансов: {str(e)}"
    
    async def get_current_bid_price(self, market_symbol: str) -> float:
        await self.init()
        url = f"{BASE_URL}/trade/public/tickers/{market_symbol}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    ticker_data = await response.json()
                    logger.info(f"✅ Получены данные тикера: {ticker_data}")
                    
                    if isinstance(ticker_data, dict):
                        if 'bid' in ticker_data:
                            return float(ticker_data['bid'])
                        elif 'buy' in ticker_data:
                            return float(ticker_data['buy'])
                return None
        except Exception as e:
            logger.error(f"❌ Ошибка при получении цены: {e}")
            return None
    
    async def create_sell_order(self, amount: float) -> str:
        await self.init()
        url = f"{BASE_URL}/trade/market/orders"
        
        current_bid_price = await self.get_current_bid_price(MARKET_SYMBOL)
        if current_bid_price is None or current_bid_price <= 0:
            return f"❌ Не удалось получить актуальную цену для {MARKET_SYMBOL}"
        
        data = {
            "market": MARKET_SYMBOL,
            "side": "sell",
            "amount": str(amount),
            "type": "limit",
            "price": str(current_bid_price)
        }
        
        try:
            headers = self.get_auth_headers()
            logger.info(f"🔄 Создаю ордер: {data}")
            
            async with self.session.post(url, headers=headers, json=data) as response:
                logger.info(f"📡 Ответ от создания ордера: статус {response.status}")
                
                if response.status == 200:
                    order_details = await response.json()
                    logger.info(f"✅ Ордер успешно создан: {order_details}")
                    
                    if 'id' in order_details:
                        # Запускаем отслеживание ордера в фоне
                        asyncio.create_task(self.track_order(order_details['id']))
                        return self.format_order_success(order_details)
                    else:
                        return f"❌ Неожиданный ответ: {order_details}"
                else:
                    error_text = await response.text()
                    return f"❌ Ошибка создания ордера: статус {response.status} - {error_text[:200]}"
                    
        except Exception as e:
            logger.error(f"❌ Ошибка при создании ордера: {e}")
            return f"❌ Ошибка при создании ордера: {str(e)}"
    
    def format_order_success(self, order_details: dict) -> str:
        return (
            f"✅ <b>Успешно размещен ордер на продажу!</b>\n\n"
            f"<b>Биржа:</b> SafeTrade\n"
            f"<b>Пара:</b> <code>{order_details.get('market', 'N/A').upper()}</code>\n"
            f"<b>Сторона:</b> <code>{order_details.get('side', 'N/A').capitalize()}</code>\n"
            f"<b>Объем:</b> <code>{order_details.get('amount', 'N/A')} {CURRENCY_TO_SELL}</code>\n"
            f"<b>Цена:</b> <code>{order_details.get('price', 'N/A')} {CURRENCY_TO_BUY}</code>\n"
            f"<b>ID ордера:</b> <code>{order_details.get('id', 'N/A')}</code>"
        )
    
    async def track_order(self, order_id: str):
        max_attempts = 30
        check_interval = 10
        logger.info(f"Начинаю отслеживание ордера {order_id}...")
        
        for attempt in range(max_attempts):
            await asyncio.sleep(check_interval)
            
            url = f"{BASE_URL}/trade/market/orders/{order_id}"
            try:
                headers = self.get_auth_headers()
                async with self.session.get(url, headers=headers) as response:
                    if response.status == 200:
                        order_info = await response.json()
                        order_state = order_info.get('state')
                        logger.info(f"Попытка {attempt+1}/{max_attempts}: Ордер {order_id} в состоянии: '{order_state}'")
                        
                        if order_state == 'done':
                            message = f"✅ <b>Ордер исполнен!</b>\n\n<b>ID ордера:</b> <code>{order_id}</code>"
                            await self.send_safe_message(ADMIN_CHAT_ID, message)
                            return
                        elif order_state == 'cancel':
                            message = f"❌ <b>Ордер отменен!</b>\n\n<b>ID ордера:</b> <code>{order_id}</code>"
                            await self.send_safe_message(ADMIN_CHAT_ID, message)
                            return
                    else:
                        logger.error(f"Ошибка получения статуса ордера: {response.status}")
                        
            except Exception as e:
                logger.error(f"Ошибка при отслеживании ордера: {e}")
        
        logger.info(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток.")
    
    async def send_safe_message(self, chat_id: str, text: str):
        """Безопасная отправка сообщения с обработкой ошибок"""
        try:
            await bot.send_message(chat_id, text)
        except TelegramRetryAfter as e:
            logger.warning(f"Флуд-контроль, жду {e.retry_after} секунд")
            await asyncio.sleep(e.retry_after)
            await bot.send_message(chat_id, text)
        except TelegramAPIError as e:
            logger.error(f"Ошибка отправки сообщения: {e}")

# Глобальный экземпляр клиента
safetrade_client = SafeTradeClient()

# --- Обработчики команд ---
@router.message(CommandStart())
async def handle_start(message: Message):
    welcome_text = """
👋 <b>Добро пожаловать в бот для управления биржей SafeTrade!</b>

<b>Доступные команды:</b>
✅ <code>/start</code> - Показать это приветственное сообщение.
💰 <code>/balance</code> - Показать ненулевые балансы.
📉 <code>/sell_qtc</code> - Продать весь доступный баланс QTC за USDT.
❤️ <code>/donate</code> - Поддержать автора.
"""
    await message.answer(welcome_text)

@router.message(Command("balance"))
async def handle_balance(message: Message):
    await message.answer("🔍 Запрашиваю балансы с SafeTrade...")
    balance_info = await safetrade_client.get_balances()
    await message.answer(balance_info)

@router.message(Command("sell_qtc"))
async def handle_sell(message: Message):
    await message.answer(f"Ищу <code>{CURRENCY_TO_SELL}</code> на балансе...")
    
    try:
        # Получаем балансы
        balances_info = await safetrade_client.get_balances()
        
        # Здесь нужно распарсить баланс QTC из ответа
        # Упрощенная версия - в реальном коде нужно распарсить ответ get_balances
        qtc_balance = 0.0  # Здесь должно быть реальное значение
        
        if qtc_balance > MIN_SELL_AMOUNT:
            await message.answer(f"✅ Обнаружено <code>{qtc_balance}</code> {CURRENCY_TO_SELL}. Создаю ордер...")
            sell_result = await safetrade_client.create_sell_order(qtc_balance)
            await message.answer(sell_result)
        else:
            await message.answer(f"Баланс <code>{CURRENCY_TO_SELL}</code> слишком мал для продажи.")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка при продаже: {str(e)}")

@router.message(Command("donate"))
async def handle_donate(message: Message):
    donate_url = "https://boosty.to/vokforever/donate"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Поддержать автора ❤️", url=donate_url)]
        ]
    )
    await message.answer(
        "Если вы хотите поддержать разработку этого бота, вы можете сделать пожертвование. Спасибо!",
        reply_markup=keyboard
    )

@router.message(Command("status"))
async def handle_status(message: Message):
    """Команда для проверки статуса бота"""
    if str(message.from_user.id) != ADMIN_CHAT_ID:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    status_text = f"""
🤖 <b>Статус бота SafeTrade</b>

⏰ <b>Время:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
📍 <b>BASE_URL:</b> <code>{BASE_URL}</code>
🆔 <b>Bot ID:</b> <code>{bot.id}</code>
👤 <b>Admin ID:</b> <code>{ADMIN_CHAT_ID}</code>
"""
    await message.answer(status_text)

# --- Обработчик ошибок ---
@router.errors()
async def error_handler(event: types.ErrorEvent):
    logger.error(f"Произошла ошибка: {event.exception}", exc_info=True)
    
    # Отправляем уведомление администратору
    with suppress(Exception):
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"⚠️ <b>Произошла ошибка в боте:</b>\n<code>{str(event.exception)[:200]}</code>"
        )

# --- Функции запуска и остановки ---
async def on_startup(dispatcher: Dispatcher):
    logger.info("🚀 Бот SafeTrade запускается...")
    
    # Удаляем вебхук
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Устанавливаем вебхук, если указан URL
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"📡 Вебхук установлен: {WEBHOOK_URL}")
    else:
        logger.info("🔄 Запускаем в режиме polling...")
    
    # Отправляем уведомление администратору
    with suppress(Exception):
        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"✅ <b>Бот SafeTrade успешно запущен!</b>\n\n"
            f"<b>Время:</b> <code>{start_time}</code>\n"
            f"<b>BASE_URL:</b> <code>{BASE_URL}</code>\n"
            f"<b>Режим:</b> <code>Вебхук</code>" if WEBHOOK_URL else "<code>Polling</code>"
        )

async def on_shutdown(dispatcher: Dispatcher):
    logger.info("🛑 Бот SafeTrade останавливается...")
    
    # Закрываем HTTP клиент
    await safetrade_client.close()
    
    # Удаляем вебхук
    await bot.delete_webhook()
    
    # Закрываем сессию бота
    await bot.session.close()
    
    logger.info("✅ Бот полностью остановлен")

# --- Основная функция запуска ---
async def main():
    # Инициализация клиента
    await safetrade_client.init()
    
    # Регистрация хуков запуска/остановки
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Запуск бота
    if WEBHOOK_URL:
        # Запуск с вебхуком
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler
        from aiohttp import web
        
        app = web.Application()
        webhook_requests_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot
        )
        
        webhook_requests_handler.register(app, path="/webhook")
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()
        
        logger.info("🚀 Сервер вебхуков запущен на порту 8080")
        
        try:
            await dp.start_polling(bot)
        finally:
            await runner.cleanup()
    else:
        # Запуск с polling
        await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен вручную")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
