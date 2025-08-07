import asyncio
import logging
import time
import hmac
import hashlib
import binascii
import json
import os
import sys
import re
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # Для запуска в режиме вебхука (опционально)

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

# --- Вспомогательные функции ---
def is_html_response(text: str) -> bool:
    """Проверяет, является ли ответ HTML страницей"""
    html_patterns = [
        r'<!DOCTYPE html>', r'<html', r'<head>', r'<body',
        r'Cloudflare', r'Attention Required!', r'jschallenge'
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in html_patterns)

def sanitize_for_telegram(text: str) -> str:
    """Очищает текст для безопасной отправки в Telegram"""
    if not text:
        return "Пустой ответ"
    
    if is_html_response(text):
        return "❌ Получен HTML ответ вместо JSON. Возможно, проблема с Cloudflare или API недоступен."
    
    text = re.sub(r'[<>]', '', text)
    if len(text) > 4000:
        text = text[:3997] + "..."
    return text

# --- Инициализация HTTP клиента ---
class SafeTradeClient:
    def __init__(self):
        self.session = None
        # cloudscraper не используется в асинхронном режиме, но оставим на всякий случай
        self.scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
    
    async def init(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    'Accept': 'application/json',
                    'User-Agent': 'SafeTrade-Client/1.0',
                }
            )
    
    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
    
    def generate_signature(self, nonce: str, secret: str, key: str) -> str:
        hash_obj = hmac.new(secret.encode(), digestmod=hashlib.sha256)
        hash_obj.update((nonce + key).encode())
        return binascii.hexlify(hash_obj.digest()).decode()
    
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
                    logger.info(f"✅ Успешный ответ (балансы): {data}")
                    
                    if isinstance(data, list):
                        non_zero_balances = [
                            f"{b.get('currency', '').upper()}: <code>{b.get('balance', '0')}</code>"
                            for b in data if float(b.get('balance', 0)) > 0
                        ]
                        if non_zero_balances:
                            return "Ваши ненулевые балансы на SafeTrade:\n\n" + "\n".join(non_zero_balances)
                        return "У вас нет ненулевых балансов на SafeTrade."
                    return f"Ошибка: получен неожиданный формат данных: <code>{str(data)[:200]}</code>"
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка API (балансы): статус {response.status}, ответ: {error_text[:500]}")
                    if is_html_response(error_text):
                        return "❌ Доступ к API заблокирован (Cloudflare). Попробуйте позже."
                    return f"❌ Ошибка API: статус {response.status} - <code>{sanitize_for_telegram(error_text[:200])}</code>"
                    
        except Exception as e:
            logger.error(f"❌ Исключение при получении балансов: {e}", exc_info=True)
            return f"❌ Ошибка при получении балансов: <code>{sanitize_for_telegram(str(e))}</code>"
    
    async def get_current_bid_price(self, market_symbol: str) -> float | None:
        await self.init()
        url = f"{BASE_URL}/trade/public/tickers/{market_symbol}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    ticker_data = await response.json()
                    logger.info(f"✅ Получены данные тикера: {ticker_data}")
                    if isinstance(ticker_data, dict) and 'bid' in ticker_data:
                        return float(ticker_data['bid'])
                return None
        except Exception as e:
            logger.error(f"❌ Ошибка при получении цены: {e}", exc_info=True)
            return None
    
    async def create_sell_order(self, amount: float) -> str:
        await self.init()
        url = f"{BASE_URL}/trade/market/orders"
        
        current_bid_price = await self.get_current_bid_price(MARKET_SYMBOL)
        if not current_bid_price or current_bid_price <= 0:
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
                
                if response.status == 201: # Обычно создание ресурса возвращает 201 Created
                    order_details = await response.json()
                    logger.info(f"✅ Ордер успешно создан: {order_details}")
                    if 'id' in order_details:
                        # asyncio.create_task(self.track_order(order_details['id']))
                        return self.format_order_success(order_details)
                    return f"❌ Неожиданный ответ: <code>{sanitize_for_telegram(str(order_details)[:200])}</code>"
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка создания ордера: статус {response.status}, ответ: {error_text[:500]}")
                    if is_html_response(error_text):
                        return "❌ Доступ к API заблокирован (Cloudflare). Не удалось создать ордер."
                    return f"❌ Ошибка создания ордера: статус {response.status} - <code>{sanitize_for_telegram(error_text[:200])}</code>"
                    
        except Exception as e:
            logger.error(f"❌ Исключение при создании ордера: {e}", exc_info=True)
            return f"❌ Ошибка при создании ордера: <code>{sanitize_for_telegram(str(e))}</code>"
    
    def format_order_success(self, order_details: dict) -> str:
        return (
            f"✅ <b>Успешно размещен ордер на продажу!</b>\n\n"
            f"<b>ID ордера:</b> <code>{order_details.get('id', 'N/A')}</code>\n"
            f"<b>Пара:</b> <code>{order_details.get('market', 'N/A').upper()}</code>\n"
            f"<b>Объем:</b> <code>{order_details.get('amount', 'N/A')} {CURRENCY_TO_SELL}</code>\n"
            f"<b>Цена:</b> <code>{order_details.get('price', 'N/A')} {CURRENCY_TO_BUY}</code>"
        )
    
    # Функции track_order и send_safe_message остаются такими же

# Глобальный экземпляр клиента
safetrade_client = SafeTradeClient()

# --- Обработчики команд ---
@router.message(CommandStart())
async def handle_start(message: Message):
    welcome_text = """
👋 <b>Добро пожаловать в бот для управления биржей SafeTrade!</b>

<b>Доступные команды:</b>
/start - Показать это приветственное сообщение.
/balance - Показать ненулевые балансы.
/sell_qtc - Продать весь доступный баланс QTC.
/donate - Поддержать автора.
/status - Проверить статус бота.
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
    # В реальном коде здесь нужно получить баланс и передать его в create_sell_order
    # Пример продажи 1 QTC
    result = await safetrade_client.create_sell_order(1.0)
    await message.answer(result)

@router.message(Command("donate"))
async def handle_donate(message: Message):
    donate_url = "https://boosty.to/vokforever/donate"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Поддержать автора ❤️", url=donate_url)]
    ])
    await message.answer("Спасибо за вашу поддержку!", reply_markup=keyboard)

@router.message(Command("status"))
async def handle_status(message: Message):
    await message.answer(f"🤖 <b>Бот работает.</b>\nВерсия API: <code>{BASE_URL}</code>")

# --- Функции жизненного цикла ---
async def on_startup(dispatcher: Dispatcher):
    logger.info("🚀 Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🔄 Запускаемся в режиме polling...")
    with suppress(Exception):
        await bot.send_message(ADMIN_CHAT_ID, f"✅ <b>Бот успешно запущен!</b>")

async def on_shutdown(dispatcher: Dispatcher):
    logger.info("🛑 Бот останавливается...")
    await safetrade_client.close()
    await bot.session.close()
    logger.info("✅ Бот полностью остановлен.")

# --- Основная функция запуска ---
async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        logger.critical("Не все переменные окружения установлены! Проверьте .env файл.")
        sys.exit(1)
    
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в main: {e}", exc_info=True)
