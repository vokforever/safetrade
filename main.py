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
import requests
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

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

# --- Инициализация HTTP клиента на основе примера SafeTrade ---
class SafeTradeClient:
    def __init__(self):
        self.session = None
        self.scraper = None
    
    async def init(self):
        if self.scraper is None:
            # Создаем сессию как в примере SafeTrade
            session = requests.Session()
            session.headers.update({
                'Content-Type': 'application/json;charset=utf-8',
                'Accept': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })
            
            # Создаем скрейпер с улучшенными настройками для обхода Cloudflare
            self.scraper = cloudscraper.create_scraper(
                sess=session,
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True,
                    'mobile': False
                },
                # Важно: отключаем JavaScript интерпретатор для стабильности
                interpreter=None,
                delay=10,
                # Добавляем дополнительные параметры для обхода защиты
                allow_brotli=True,
                ecdhCurve='secp384r1'
            )
            
            # Сначала делаем запрос на главную страницу для получения cookies
            try:
                logger.info("🔄 Получаю cookies с главной страницы...")
                response = self.scraper.get("https://safe.trade", timeout=30)
                logger.info(f"✅ Cookies получены, статус: {response.status_code}")
                
                # Дополнительный запрос к API для инициализации сессии
                init_response = self.scraper.get(f"{BASE_URL}/trade/public/tickers/{MARKET_SYMBOL}", timeout=30)
                logger.info(f"✅ Инициализация API сессии, статус: {init_response.status_code}")
                
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при получении cookies: {e}")
    
    async def close(self):
        # Закрываем сессию скрейпера
        if self.scraper:
            if hasattr(self.scraper, 'close'):
                self.scraper.close()
            self.scraper = None
    
    def generate_signature(self, nonce: str, secret: str, key: str) -> str:
        """Генерация подписи как в примере SafeTrade"""
        hash_obj = hmac.new(secret.encode(), digestmod=hashlib.sha256)
        hash_obj.update((nonce + key).encode())
        signature = hash_obj.digest()
        return binascii.hexlify(signature).decode()
    
    def get_auth_headers(self) -> dict:
        """Заголовки аутентификации как в примере SafeTrade"""
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
        """Получение балансов как в примере SafeTrade"""
        await self.init()
        
        # Пробуем разные эндпоинты как в примере
        endpoints = [
            f"{BASE_URL}/trade/account/balances",
            f"{BASE_URL}/peatio/account/balances",
            f"{BASE_URL}/account/balances"
        ]
        
        for endpoint in endpoints:
            try:
                headers = self.get_auth_headers()
                logger.info(f"🔄 Пробую эндпоинт: {endpoint}")
                
                # Используем синхронный запрос как в примере
                response = self.scraper.get(endpoint, headers=headers, timeout=30)
                logger.info(f"📡 Ответ от {endpoint}: статус {response.status_code}")
                
                if response.status_code == 200:
                    # Проверяем, что это JSON
                    try:
                        data = response.json()
                        logger.info(f"✅ Успешный JSON ответ: {data}")
                        
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
                            return f"Ошибка: получен неожиданный формат данных: <code>{str(data)[:200]}</code>"
                    except json.JSONDecodeError:
                        logger.error(f"❌ Получен не-JSON ответ от {endpoint}")
                        continue
                        
                elif response.status_code == 403:
                    logger.error(f"❌ Доступ запрещен к {endpoint} (Cloudflare)")
                    # Если все эндпоинты возвращают 403, пробуем альтернативный подход
                    continue
                else:
                    logger.error(f"❌ Ошибка {response.status_code} для {endpoint}")
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Исключение при запросе к {endpoint}: {e}")
                continue
        
        # Если все эндпоинты не сработали, пробуем альтернативный метод
        return await self.alternative_get_balances()
    
    async def alternative_get_balances(self) -> str:
        """Альтернативный метод получения балансов через прокси или другой подход"""
        try:
            logger.info("🔄 Пробую альтернативный метод получения балансов...")
            
            # Метод 1: Используем aiohttp с прокси-заголовками
            headers = self.get_auth_headers()
            headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            
            # Пробуем сделать запрос через aiohttp
            if not self.session:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers=headers
                )
            
            async with self.session.get(f"{BASE_URL}/trade/account/balances") as response:
                logger.info(f"📡 Альтернативный запрос, статус: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"✅ Альтернативный метод успешен: {data}")
                    
                    if isinstance(data, list):
                        non_zero_balances = [
                            f"{b.get('currency', '').upper()}: <code>{b.get('balance', '0')}</code>"
                            for b in data if float(b.get('balance', 0)) > 0
                        ]
                        
                        if non_zero_balances:
                            return "Ваши ненулевые балансы на SafeTrade (альтернативный метод):\n\n" + "\n".join(non_zero_balances)
                        else:
                            return "У вас нет ненулевых балансов на SafeTrade."
                
        except Exception as e:
            logger.error(f"❌ Альтернативный метод тоже не сработал: {e}")
        
        return "❌ Не удалось получить балансы. Все методы доступа к API заблокированы Cloudflare. Проверьте API ключи или попробуйте позже."
    
    async def get_current_bid_price(self, market_symbol: str) -> float:
        """Получение текущей цены"""
        await self.init()
        
        try:
            # Сначала пробуем публичный эндпоинт (без аутентификации)
            url = f"{BASE_URL}/trade/public/tickers/{market_symbol}"
            response = self.scraper.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Получены данные тикера: {data}")
                
                if isinstance(data, dict):
                    # Пробуем разные форматы ответа
                    if 'bid' in data:
                        return float(data['bid'])
                    elif 'buy' in data:
                        return float(data['buy'])
                    elif 'ticker' in data and isinstance(data['ticker'], dict):
                        ticker = data['ticker']
                        if 'bid' in ticker:
                            return float(ticker['bid'])
                        elif 'buy' in ticker:
                            return float(ticker['buy'])
                        
        except Exception as e:
            logger.error(f"❌ Ошибка при получении цены: {e}")
        
        return None
    
    async def create_sell_order(self, amount: float) -> str:
        """Создание ордера на продажу"""
        await self.init()
        
        current_bid_price = await self.get_current_bid_price(MARKET_SYMBOL)
        if current_bid_price is None or current_bid_price <= 0:
            return f"❌ Не удалось получить актуальную цену для {MARKET_SYMBOL}"
        
        # Формируем данные как в примере SafeTrade
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
            
            # Используем синхронный POST запрос как в примере
            response = self.scraper.post(
                f"{BASE_URL}/trade/market/orders",
                headers=headers,
                json=data,
                timeout=30
            )
            
            logger.info(f"📡 Ответ от создания ордера: статус {response.status_code}")
            
            if response.status_code == 200:
                order_details = response.json()
                logger.info(f"✅ Ордер успешно создан: {order_details}")
                
                if 'id' in order_details:
                    asyncio.create_task(self.track_order(order_details['id']))
                    return self.format_order_success(order_details)
                else:
                    return f"❌ Неожиданный ответ: <code>{str(order_details)[:200]}</code>"
            else:
                error_text = response.text
                logger.error(f"Ошибка создания ордера: {error_text[:500]}")
                return f"❌ Ошибка создания ордера: статус {response.status_code}"
                
        except Exception as e:
            logger.error(f"❌ Ошибка при создании ордера: {e}")
            return f"❌ Ошибка при создании ордера: <code>{str(e)[:200]}</code>"
    
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
            
            try:
                headers = self.get_auth_headers()
                response = self.scraper.get(
                    f"{BASE_URL}/trade/market/orders/{order_id}",
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    order_info = response.json()
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
                        
            except Exception as e:
                logger.error(f"Ошибка при отслеживании ордера: {e}")
        
        logger.info(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток.")
    
    async def send_safe_message(self, chat_id: str, text: str):
        """Безопасная отправка сообщения"""
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
🔧 <code>/status</code> - Проверить статус бота.
🔄 <code>/test_api</code> - Тестировать подключение к API.
"""
    await message.answer(welcome_text)

@router.message(Command("balance"))
async def handle_balance(message: Message):
    await message.answer("🔍 Запрашиваю балансы с SafeTrade...")
    balance_info = await safetrade_client.get_balances()
    await message.answer(balance_info)

@router.message(Command("test_api"))
async def handle_test_api(message: Message):
    """Тестирование подключения к API"""
    await message.answer("🔄 Тестирую подключение к SafeTrade API...")
    
    try:
        await safetrade_client.init()
        
        # Тестируем публичный эндпоинт
        test_url = f"{BASE_URL}/trade/public/tickers/{MARKET_SYMBOL}"
        response = safetrade_client.scraper.get(test_url, timeout=30)
        
        if response.status_code == 200:
            await message.answer(f"✅ Подключение к API успешно!\nСтатус: {response.status_code}\nURL: {test_url}")
        else:
            await message.answer(f"❌ Ошибка подключения: {response.status_code}\n{response.text[:200]}")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка при тестировании API: <code>{str(e)[:200]}</code>")

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
    status_text = f"""
🤖 <b>Статус бота SafeTrade</b>

⏰ <b>Время:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
📍 <b>BASE_URL:</b> <code>{BASE_URL}</code>
🆔 <b>Bot ID:</b> <code>{bot.id}</code>
👤 <b>Ваш ID:</b> <code>{message.from_user.id}</code>
"""
    await message.answer(status_text)

# --- Обработчик ошибок ---
@router.errors()
async def error_handler(event: types.ErrorEvent):
    logger.error(f"Произошла ошибка: {event.exception}", exc_info=True)
    
    with suppress(Exception):
        error_msg = str(event.exception)
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"⚠️ <b>Произошла ошибка в боте:</b>\n<code>{error_msg[:500]}</code>"
        )

# --- Функции запуска и остановки ---
async def on_startup(dispatcher: Dispatcher):
    logger.info("🚀 Бот SafeTrade запускается...")
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"📡 Вебхук установлен: {WEBHOOK_URL}")
    else:
        logger.info("🔄 Запускаем в режиме polling...")
    
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
    
    await safetrade_client.close()
    await bot.delete_webhook()
    await bot.session.close()
    
    logger.info("✅ Бот полностью остановлен")

# --- Основная функция запуска ---
async def main():
    await safetrade_client.init()
    
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    if WEBHOOK_URL:
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
        await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен вручную")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
