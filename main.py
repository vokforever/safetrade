# Перед запуском убедитесь, что у вас есть файл requirements.txt с таким содержимым:
#
# aiogram==3.10.0
# requests==2.32.3
# cloudscraper==1.2.71
# python-dotenv==1.0.1
# apscheduler==3.10.4
#

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

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# --- 1. Настройка ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

SELL_INTERVAL_HOURS = float(os.getenv("SELL_INTERVAL_HOURS", "1"))
BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
MIN_SELL_AMOUNT = 0.00000001

# --- 2. Инициализация ---
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)
scheduler = AsyncIOScheduler()

# --- 3. Класс для работы с API SafeTrade ---
class SafeTradeClient:
    def __init__(self):
        self.scraper = None
        self.base_url = BASE_URL

    async def init(self):
        if self.scraper is not None:
            return
        session = requests.Session()
        session.headers.update({
            'Content-Type': 'application/json;charset=utf-8', 'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.scraper = cloudscraper.create_scraper(sess=session)
        try:
            logger.info("🔄 Прогреваю сессию для обхода Cloudflare...")
            await asyncio.to_thread(self.scraper.get, "https://safe.trade", timeout=30)
            logger.info("✅ Сессия успешно прогрета.")
        except Exception as e:
            logger.error(f"⚠️ Критическая ошибка при инициализации клиента: {e}")
            self.scraper = None

    async def close(self):
        if self.scraper and hasattr(self.scraper, 'close'):
            self.scraper.close()

    def get_auth_headers(self) -> dict:
        nonce = str(int(time.time() * 1000))
        if not API_KEY or not API_SECRET: raise ValueError("API Key/Secret не установлены.")
        hash_obj = hmac.new(API_SECRET.encode(), (nonce + API_KEY).encode(), hashlib.sha256)
        signature = binascii.hexlify(hash_obj.digest()).decode()
        return {"X-Auth-Apikey": API_KEY, "X-Auth-Nonce": nonce, "X-Auth-Signature": signature}

    async def _get_raw_balances(self) -> list | None:
        await self.init()
        if not self.scraper: return None
        for endpoint in [f"{self.base_url}/trade/account/balances", f"{self.base_url}/peatio/account/balances"]:
            try:
                response = await asyncio.to_thread(self.scraper.get, endpoint, headers=self.get_auth_headers(), timeout=30)
                if response.status_code == 200: return response.json()
            except Exception as e: logger.error(f"❌ Исключение при запросе балансов к {endpoint}: {e}")
        return None

    async def get_balances_string(self) -> str:
        raw_balances = await self._get_raw_balances()
        if raw_balances is None: return "❌ Не удалось получить балансы."
        balances = [f"{b['currency'].upper()}: <code>{b['balance']}</code>" for b in raw_balances if float(b.get('balance', 0)) > 0]
        return "Ваши ненулевые балансы:\n\n" + "\n".join(balances) if balances else "У вас нет ненулевых балансов."

    async def get_specific_balance(self, currency: str) -> float | None:
        raw_balances = await self._get_raw_balances()
        if raw_balances:
            for item in raw_balances:
                if item.get('currency', '').lower() == currency.lower(): return float(item.get('balance', 0.0))
        return None
    
    # НОВЫЙ МЕТОД
    async def get_trade_history(self, market: str, limit: int = 10) -> str:
        """Получает историю сделок для указанного рынка."""
        await self.init()
        if not self.scraper:
            return "❌ Не удалось получить историю: клиент не инициализирован."
        
        try:
            url = f"{self.base_url}/trade/market/trades?market={market}&limit={limit}"
            response = await asyncio.to_thread(self.scraper.get, url, headers=self.get_auth_headers(), timeout=30)
            
            if response.status_code == 200:
                trades = response.json()
                if not trades:
                    return f"Пока нет истории сделок для пары <b>{market.upper()}</b>."
                
                history_lines = []
                for trade in trades:
                    # 'taker_type' показывает, кем вы были в сделке: 'sell' (продали) или 'buy' (купили)
                    trade_type = "SELL" if trade.get('taker_type') == 'sell' else "BUY"
                    color = "🔴" if trade_type == "SELL" else "🟢"
                    
                    # API возвращает время в формате ISO 8601 с 'Z' на конце
                    dt_object = datetime.fromisoformat(trade.get('created_at').replace('Z', '+00:00'))
                    readable_time = dt_object.strftime('%Y-%m-%d %H:%M:%S')

                    history_lines.append(
                        f"{color} <b>{trade.get('market').upper()}</b>\n"
                        f"    <b>Тип:</b> {trade_type}\n"
                        f"    <b>Кол-во:</b> <code>{trade.get('amount')}</code>\n"
                        f"    <b>Цена:</b> <code>{trade.get('price')}</code>\n"
                        f"    <b>Время:</b> <code>{readable_time}</code>"
                    )
                return "📈 <b>Последние 10 сделок:</b>\n\n" + "\n".join(history_lines)
            else:
                return f"❌ Ошибка получения истории: статус {response.status_code}"

        except Exception as e:
            logger.error(f"❌ Исключение при получении истории сделок: {e}", exc_info=True)
            return f"❌ Исключение при получении истории: <code>{e}</code>"

    async def get_order_status(self, order_id: int) -> dict | None:
        await self.init()
        if not self.scraper: return None
        try:
            url = f"{self.base_url}/trade/market/orders/{order_id}"
            response = await asyncio.to_thread(self.scraper.get, url, headers=self.get_auth_headers(), timeout=30)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Исключение при получении статуса ордера {order_id}: {e}")
            return None

    async def create_market_sell_order(self, amount: float) -> str:
        await self.init()
        if not self.scraper: return "❌ Не удалось создать ордер: клиент не инициализирован."
        data = {"market": MARKET_SYMBOL, "side": "sell", "amount": str(amount), "type": "market"}
        try:
            logger.info(f"🔄 Создаю MARKET ордер: {data}")
            response = await asyncio.to_thread(self.scraper.post, f"{self.base_url}/trade/market/orders", headers=self.get_auth_headers(), json=data, timeout=30)
            if response.status_code in [200, 201]:
                order_details = response.json()
                if 'id' in order_details:
                    asyncio.create_task(self.track_order_execution(order_details['id']))
                    return self.format_order_creation_success(order_details)
                return f"❌ Неожиданный ответ: <code>{str(order_details)[:200]}</code>"
            return f"❌ Ошибка создания ордера: статус {response.status_code}. Ответ: <code>{response.text[:200]}</code>"
        except Exception as e:
            logger.error(f"❌ Исключение при создании ордера: {e}", exc_info=True)
            return f"❌ Исключение при создании ордера: <code>{str(e)[:200]}</code>"

    async def track_order_execution(self, order_id: int):
        logger.info(f"Начинаю отслеживание исполнения ордера {order_id}...")
        max_attempts = 60
        for attempt in range(max_attempts):
            await asyncio.sleep(10)
            order_info = await self.get_order_status(order_id)
            if not order_info: continue
            state = order_info.get('state')
            logger.info(f"Попытка {attempt+1}/{max_attempts}: Ордер {order_id} в состоянии '{state}'")
            if state == 'done':
                message = (f"✅ <b>Ордер #{order_id} исполнен!</b>\n\n"
                           f"<b>Продано:</b> <code>{order_info.get('executed_volume', 'N/A')} {CURRENCY_TO_SELL}</code>\n"
                           f"<b>Средняя цена:</b> <code>{order_info.get('avg_price', 'N/A')} {CURRENCY_TO_BUY}</code>")
                await bot.send_message(ADMIN_CHAT_ID, message)
                return
            if state in ['cancel', 'reject']:
                await bot.send_message(ADMIN_CHAT_ID, f"❌ <b>Ордер #{order_id} был отменен или отклонен.</b>")
                return
        await bot.send_message(ADMIN_CHAT_ID, f"⚠️ Ордер #{order_id} не был исполнен за 10 минут.")

    def format_order_creation_success(self, order: dict) -> str:
        return (f"✅ <b>Рыночный ордер на продажу создан!</b>\n\n"
                f"<b>Пара:</b> <code>{order.get('market', 'N/A').upper()}</code>\n"
                f"<b>Заявленный объем:</b> <code>{order.get('amount', 'N/A')} {CURRENCY_TO_SELL}</code>\n"
                f"<b>ID для отслеживания:</b> <code>{order.get('id', 'N/A')}</code>\n\n"
                f"⏳ Ожидаю исполнения...")

safetrade_client = SafeTradeClient()

# --- 4. Задача для автоматической продажи ---
async def scheduled_sell_task():
    logger.info(f"--- 🗓️ Запуск автоматической продажи {CURRENCY_TO_SELL} ---")
    try:
        balance = await safetrade_client.get_specific_balance(CURRENCY_TO_SELL)
        if balance is None or balance <= MIN_SELL_AMOUNT:
            logger.info(f"🗓️ Задача завершена: баланс ({balance or 0}) недостаточен.")
            return
        logger.info(f"🗓️ Баланс {balance} {CURRENCY_TO_SELL} достаточен. Создаю рыночный ордер...")
        result_message = await safetrade_client.create_market_sell_order(balance)
        await bot.send_message(ADMIN_CHAT_ID, "📈 <b>Автоматическая продажа:</b>\n\n" + result_message)
    except Exception as e:
        logger.error(f"🗓️ КРИТИЧЕСКАЯ ОШИБКА в задаче авто-продажи: {e}", exc_info=True)
        await bot.send_message(ADMIN_CHAT_ID, f"⚠️ <b>Ошибка в задаче авто-продажи:</b>\n<code>{str(e)}</code>")

# --- 5. Обработчики команд Telegram ---
@router.message(CommandStart())
async def handle_start(message: Message):
    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "<b>Команды:</b>\n"
        "💰 <code>/balance</code> - Показать балансы\n"
        "📉 <code>/sell_qtc</code> - Продать весь QTC по рынку\n"
        "📜 <code>/history</code> - Показать историю сделок\n"
        "❤️ <code>/donate</code> - Поддержать автора"
    )

@router.message(Command("balance"))
async def handle_balance(message: Message):
    await message.answer("🔍 Запрашиваю балансы...")
    balance_info = await safetrade_client.get_balances_string()
    await message.answer(balance_info)

# НОВЫЙ ОБРАБОТЧИК
@router.message(Command("history"))
async def handle_history(message: Message):
    await message.answer("🔍 Запрашиваю историю сделок...")
    history_info = await safetrade_client.get_trade_history(MARKET_SYMBOL)
    await message.answer(history_info)

@router.message(Command("sell_qtc"))
async def handle_sell_qtc(message: Message):
    await message.answer(f"🔍 Инициирую продажу {CURRENCY_TO_SELL} по рынку...")
    balance = await safetrade_client.get_specific_balance(CURRENCY_TO_SELL)
    if balance is None or balance <= MIN_SELL_AMOUNT:
        await message.answer(f"ℹ️ Ваш баланс {CURRENCY_TO_SELL} ({balance or 0}) слишком мал для продажи.")
        return
    result = await safetrade_client.create_market_sell_order(balance)
    await message.answer(result)

@router.message(Command("donate"))
async def handle_donate(message: Message):
    await message.answer("Спасибо за желание поддержать ❤️", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Поддержать автора", url="https://boosty.to/vokforever/donate")]]
    ))

# --- 6. Жизненный цикл бота ---
async def on_startup(dispatcher: Dispatcher):
    logger.info("🚀 Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    if SELL_INTERVAL_HOURS > 0:
        scheduler.add_job(scheduled_sell_task, IntervalTrigger(hours=SELL_INTERVAL_HOURS), name='Auto-Sell Task')
        scheduler.start()
        logger.info(f"✅ Планировщик запущен: авто-продажа каждые {SELL_INTERVAL_HOURS} час(а).")
    else:
        logger.info("ℹ️ Автоматическая продажа по расписанию отключена.")
    await bot.send_message(ADMIN_CHAT_ID, "✅ <b>Бот успешно запущен!</b>")

async def on_shutdown(dispatcher: Dispatcher):
    logger.info("🛑 Бот останавливается...")
    if scheduler.running: scheduler.shutdown()
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
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        logger.critical("❌ Критическая ошибка: Не все переменные окружения установлены.")
        sys.exit(1)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен вручную.")
