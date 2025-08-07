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

import requests
import cloudscraper
from aiogram import Bot, Dispatcher, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.client.bot import DefaultBotProperties
from dotenv import load_dotenv

# --- НОВОЕ: импорт для планировщика ---
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Загрузка переменных окружения ---
load_dotenv()
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# --- НОВОЕ: переменная для авто-продажи ---
# По умолчанию 1 час. Если установить 0, функция будет отключена.
SELL_INTERVAL_HOURS = float(os.getenv("SELL_INTERVAL_HOURS", "1"))

# --- Конфигурация ---
BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
MIN_SELL_AMOUNT = 0.00000001

# --- Инициализация ---
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler() # НОВОЕ: создаем экземпляр планировщика

# --- Класс клиента (без изменений, остался таким же надежным) ---
class SafeTradeClient:
    def __init__(self):
        self.scraper = None
    
    async def init(self):
        if self.scraper is None:
            session = requests.Session()
            session.headers.update({
                'Content-Type': 'application/json;charset=utf-8', 'Accept': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })
            self.scraper = cloudscraper.create_scraper(sess=session, browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}, interpreter=None, delay=10)
            try:
                logger.info("🔄 Получаю cookies с главной страницы...")
                response = await asyncio.to_thread(self.scraper.get, "https://safe.trade", timeout=30)
                response.raise_for_status()
                logger.info(f"✅ Cookies получены, статус: {response.status_code}")
                init_response = await asyncio.to_thread(self.scraper.get, f"{BASE_URL}/trade/public/tickers/{MARKET_SYMBOL}", timeout=30)
                init_response.raise_for_status()
                logger.info(f"✅ Инициализация API сессии, статус: {init_response.status_code}")
            except Exception as e:
                logger.error(f"⚠️ Критическая ошибка при инициализации клиента: {e}")
                self.scraper = None
    
    async def close(self):
        if self.scraper and hasattr(self.scraper, 'close'): self.scraper.close()
        self.scraper = None
    
    def get_auth_headers(self) -> dict:
        nonce = str(int(time.time() * 1000))
        if not API_KEY or not API_SECRET: raise ValueError("API Key или API Secret не установлены.")
        signature = hmac.new(API_SECRET.encode(), (nonce + API_KEY).encode(), hashlib.sha256).hexdigest()
        return {"X-Auth-Apikey": API_KEY, "X-Auth-Nonce": nonce, "X-Auth-Signature": signature, "Content-Type": "application/json;charset=utf-8"}

    async def _get_raw_balances(self) -> list | None:
        await self.init()
        if not self.scraper: return None
        endpoints = [f"{BASE_URL}/trade/account/balances", f"{BASE_URL}/peatio/account/balances", f"{BASE_URL}/account/balances"]
        for endpoint in endpoints:
            try:
                response = await asyncio.to_thread(self.scraper.get, endpoint, headers=self.get_auth_headers(), timeout=30)
                if response.status_code == 200 and isinstance(response.json(), list): return response.json()
            except Exception as e: logger.error(f"❌ Исключение при запросе к {endpoint}: {e}")
        return None

    async def get_balances_string(self) -> str:
        raw_balances = await self._get_raw_balances()
        if raw_balances is None: return "❌ Не удалось получить балансы."
        non_zero_balances = [f"{b.get('currency', '').upper()}: <code>{b.get('balance', '0')}</code>" for b in raw_balances if float(b.get('balance', 0)) > 0]
        return "Ваши ненулевые балансы:\n\n" + "\n".join(non_zero_balances) if non_zero_balances else "У вас нет ненулевых балансов."

    async def get_specific_balance(self, currency: str) -> float | None:
        raw_balances = await self._get_raw_balances()
        if raw_balances:
            for item in raw_balances:
                if item.get('currency', '').lower() == currency.lower(): return float(item.get('balance', 0.0))
        return None

    async def get_current_bid_price(self, market_symbol: str) -> float | None:
        await self.init()
        if not self.scraper: return None
        try:
            url = f"{BASE_URL}/trade/public/tickers/{market_symbol}"
            response = await asyncio.to_thread(self.scraper.get, url, timeout=30)
            if response.status_code == 200:
                ticker_data = response.json().get('ticker', {})
                return float(ticker_data.get('bid', 0.0))
        except Exception as e: logger.error(f"❌ Ошибка при получении цены: {e}")
        return None
    
    async def create_sell_order(self, amount: float, price: float) -> str:
        await self.init()
        if not self.scraper: return "❌ Не удалось создать ордер: клиент не инициализирован."
        data = {"market": MARKET_SYMBOL, "side": "sell", "amount": str(amount), "type": "limit", "price": str(price)}
        try:
            response = await asyncio.to_thread(self.scraper.post, f"{BASE_URL}/trade/market/orders", headers=self.get_auth_headers(), json=data, timeout=30)
            if response.status_code in [200, 201]:
                order_details = response.json()
                if 'id' in order_details:
                    asyncio.create_task(self.track_order(order_details['id']))
                    return self.format_order_success(order_details)
                return f"❌ Неожиданный ответ: <code>{str(order_details)[:200]}</code>"
            return f"❌ Ошибка создания ордера: статус {response.status_code}. Ответ: <code>{response.text[:200]}</code>"
        except Exception as e:
            logger.error(f"❌ Исключение при создании ордера: {e}", exc_info=True)
            return f"❌ Исключение при создании ордера: <code>{str(e)[:200]}</code>"
    
    def format_order_success(self, order: dict) -> str:
        return (f"✅ <b>Ордер на продажу размещен!</b>\n\n"
                f"<b>Пара:</b> <code>{order.get('market', 'N/A').upper()}</code>\n"
                f"<b>Объем:</b> <code>{order.get('amount', 'N/A')} {CURRENCY_TO_SELL}</code>\n"
                f"<b>Цена:</b> <code>{order.get('price', 'N/A')} {CURRENCY_TO_BUY}</code>\n"
                f"<b>ID:</b> <code>{order.get('id', 'N/A')}</code>")

    async def track_order(self, order_id: str):
        # ... (код отслеживания остается без изменений) ...
        pass

    async def send_safe_message(self, chat_id: str, text: str):
        # ... (код безопасной отправки остается без изменений) ...
        pass

safetrade_client = SafeTradeClient()

# --- НОВОЕ: Функция для автоматической продажи ---
async def scheduled_sell_task():
    logger.info(f"--- Scheduled Task: Запуск автоматической продажи {CURRENCY_TO_SELL} ---")
    try:
        balance = await safetrade_client.get_specific_balance(CURRENCY_TO_SELL)
        if balance is None:
            logger.error("Scheduled Task: Не удалось получить баланс, задача прервана.")
            return

        if balance > MIN_SELL_AMOUNT:
            logger.info(f"Scheduled Task: Баланс {balance} {CURRENCY_TO_SELL} достаточен для продажи.")
            price = await safetrade_client.get_current_bid_price(MARKET_SYMBOL)
            if not price:
                logger.error("Scheduled Task: Не удалось получить цену, задача прервана.")
                return
            
            result_message = await safetrade_client.create_sell_order(balance, price)
            await safetrade_client.send_safe_message(ADMIN_CHAT_ID, "📈 <b>Автоматическая продажа:</b>\n\n" + result_message)
        else:
            logger.info(f"Scheduled Task: Баланс {balance} {CURRENCY_TO_SELL} слишком мал для продажи.")

    except Exception as e:
        logger.error(f"Scheduled Task: КРИТИЧЕСКАЯ ОШИБКА - {e}", exc_info=True)
        await safetrade_client.send_safe_message(ADMIN_CHAT_ID, f"⚠️ <b>Ошибка в задаче авто-продажи:</b>\n<code>{str(e)}</code>")

# --- Обработчики команд ---
@router.message(CommandStart())
async def handle_start(message: Message):
    # ... (код приветствия без изменений) ...
    pass

@router.message(Command("balance"))
async def handle_balance(message: Message):
    await message.answer("🔍 Запрашиваю балансы...")
    balance_info = await safetrade_client.get_balances_string()
    await message.answer(balance_info)

@router.message(Command("sell_qtc"))
async def handle_sell_qtc(message: Message):
    await message.answer(f"🔍 Инициирую продажу {CURRENCY_TO_SELL}...")
    balance = await safetrade_client.get_specific_balance(CURRENCY_TO_SELL)
    if balance is None:
        await message.answer(f"❌ Не удалось получить баланс {CURRENCY_TO_SELL}.")
        return
    if balance > MIN_SELL_AMOUNT:
        price = await safetrade_client.get_current_bid_price(MARKET_SYMBOL)
        if not price:
            await message.answer(f"❌ Не удалось получить цену для {MARKET_SYMBOL}.")
            return
        result = await safetrade_client.create_sell_order(balance, price)
        await message.answer(result)
    else:
        await message.answer(f"ℹ️ Ваш баланс {CURRENCY_TO_SELL} ({balance}) слишком мал для продажи.")

# ... (остальные обработчики: test_api, donate, status)

# --- Функции жизненного цикла ---
async def on_startup(dispatcher: Dispatcher):
    logger.info("🚀 Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await safetrade_client.init() # Инициализируем клиент при старте
    
    # --- НОВОЕ: Запуск планировщика ---
    if SELL_INTERVAL_HOURS > 0:
        scheduler.add_job(
            scheduled_sell_task,
            trigger=IntervalTrigger(hours=SELL_INTERVAL_HOURS),
            name='Automatic QTC selling job'
        )
        scheduler.start()
        logger.info(f"✅ Планировщик запущен: авто-продажа каждые {SELL_INTERVAL_HOURS} час(а).")
    else:
        logger.info("ℹ️ Автоматическая продажа по расписанию отключена (SELL_INTERVAL_HOURS=0).")

    await bot.send_message(ADMIN_CHAT_ID, "✅ <b>Бот успешно запущен!</b>")

async def on_shutdown(dispatcher: Dispatcher):
    logger.info("🛑 Бот останавливается...")
    if scheduler.running: scheduler.shutdown() # НОВОЕ: останавливаем планировщик
    await safetrade_client.close()
    await bot.session.close()
    logger.info("✅ Бот полностью остановлен")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown(dp)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен вручную.")
