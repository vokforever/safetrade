import time
import hmac
import hashlib
import json
import os
import telebot
from telebot import types
from dotenv import load_dotenv
import cloudscraper
from datetime import datetime, timedelta
import threading
from supabase import create_client, Client
from cerebras.cloud.sdk import Cerebras
import requests
from pathlib import Path
import random
import math
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import sys
import signal
from threading import Lock, Semaphore
from tenacity import retry, stop_after_attempt, wait_exponential
from contextlib import contextmanager
import asyncio
import aiohttp
from collections import deque
import yaml
import socket
import subprocess
from urllib.parse import urlparse

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- ФУНКЦИИ ПРОВЕРКИ СЕТЕВОГО ПОДКЛЮЧЕНИЯ ---
def check_network_connectivity():
    """Проверка сетевого подключения и DNS резолюции"""
    try:
        # Проверяем DNS резолюцию
        socket.gethostbyname('api.telegram.org')
        logging.info("DNS резолюция для api.telegram.org: ОК")
        
        # Проверяем HTTP подключение
        response = requests.get('https://api.telegram.org', timeout=10)
        logging.info("HTTP подключение к api.telegram.org: ОК")
        return True
    except socket.gaierror as e:
        logging.error(f"DNS ошибка: {e}")
        return False
    except Exception as e:
        logging.error(f"Сетевая ошибка: {e}")
        return False

def configure_dns():
    """Конфигурация альтернативных DNS серверов"""
    try:
        # Для Linux контейнеров - добавляем Google DNS
        dns_config = """
nameserver 8.8.8.8
nameserver 8.8.4.4
nameserver 1.1.1.1
"""
        with open('/etc/resolv.conf', 'a') as f:
            f.write(dns_config)
        logging.info("DNS серверы настроены")
    except Exception as e:
        logging.warning(f"Не удалось настроить DNS: {e}")

# --- ЗАГРУЗКА КОНФИГУРАЦИИ ---
load_dotenv()
# Конфигурация по умолчанию
# 
# ОБЯЗАТЕЛЬНЫЕ переменные окружения (для работы бота):
# - SAFETRADE_API_KEY - API ключ SafeTrade
# - SAFETRADE_API_SECRET - API секрет SafeTrade
#
# ОПЦИОНАЛЬНЫЕ переменные окружения (для расширенного функционала):
# - SAFETRADE_TELEGRAM_BOT_TOKEN - Токен Telegram бота (для Telegram интерфейса)
# - SAFETRADE_ADMIN_CHAT_ID - ID чата администратора (для уведомлений)
# - SAFETRADE_CEREBRAS_API_KEY - API ключ Cerebras AI (для ИИ-помощника)
# - SAFETRADE_SUPABASE_URL - URL Supabase (для облачной базы данных)
# - SAFETRADE_SUPABASE_KEY - Ключ Supabase (для облачной базы данных)
# - SAFETRADE_WEBHOOK_URL - URL для webhook режима (альтернатива polling)
# - SAFETRADE_WEBHOOK_PORT - Порт для webhook режима
#
# ПРИМЕЧАНИЕ: Бот будет работать ТОЛЬКО с SAFETRADE_API_KEY и SAFETRADE_API_SECRET!
# Все остальные функции будут отключены, если соответствующие переменные не указаны.
DEFAULT_CONFIG = {
    'trading': {
        'excluded_currencies': ['USDT', 'BUSD', 'USDC'],
        'min_position_value_usd': 1.0,
        'max_concurrent_sales': 3,
        'auto_sell_interval': 3600,
        'strategies': {
            'twap': {
                'default_duration': 60,
                'default_chunks': 6
            },
            'iceberg': {
                'default_visible_ratio': 0.1,
                'max_attempts': 20
            },
            'adaptive': {
                'max_price_levels': 10,
                'liquidity_ratio': 0.1
            }
        }
    },
    'risk_management': {
        'max_position_value': 10000,
        'min_spread_threshold': 0.001,
        'max_volatility_threshold': 0.05
    },
    'cache': {
        'markets_duration': 14400,  # 4 часа
        'prices_duration': 300,     # 5 минут
        'orderbook_duration': 60    # 1 минута
    }
}

# Загрузка конфигурации из файла
def load_config():
    config_path = Path("config.yml")
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                custom_config = yaml.safe_load(f)
            # Объединяем с конфигурацией по умолчанию
            return {**DEFAULT_CONFIG, **custom_config}
        except Exception as e:
            logging.warning(f"Ошибка загрузки конфигурации: {e}. Используется конфигурация по умолчанию.")
    return DEFAULT_CONFIG

CONFIG = load_config()

# Загружаем токены и ID из переменных окружения
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("SAFETRADE_TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("SAFETRADE_ADMIN_CHAT_ID")
CEREBRAS_API_KEY = os.getenv("SAFETRADE_CEREBRAS_API_KEY")

# Supabase настройки
SUPABASE_URL = os.getenv("SAFETRADE_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SAFETRADE_SUPABASE_KEY")

# URL для пожертвований
DONATE_URL = "https://boosty.to/vokforever/donate"

# Убедимся, что секрет в байтовом представлении для hmac
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None
BASE_URL = "https://safe.trade/api/v2"

# Настройки из конфигурации
EXCLUDED_CURRENCIES = CONFIG['trading']['excluded_currencies']
MIN_POSITION_VALUE_USD = CONFIG['trading']['min_position_value_usd']
MAX_CONCURRENT_SALES = CONFIG['trading']['max_concurrent_sales']
AUTO_SELL_INTERVAL = CONFIG['trading']['auto_sell_interval']

# Кэширование с locks для thread safety
cache_lock = Lock()
markets_cache = {
    "data": [],
    "last_update": None,
    "cache_duration": CONFIG['cache']['markets_duration']
}
prices_cache = {
    "data": {},
    "last_update": None,
    "cache_duration": CONFIG['cache']['prices_duration']
}
orderbook_cache = {
    "data": {},
    "last_update": {},
    "cache_duration": CONFIG['cache']['orderbook_duration']
}

# Semaphore для ограничения concurrent продаж
sales_sem = Semaphore(MAX_CONCURRENT_SALES)

# Стратегии продаж
class SellStrategy(Enum):
    MARKET = "market"
    LIMIT = "limit"
    TWAP = "twap"
    ICEBERG = "iceberg"
    ADAPTIVE = "adaptive"

class OrderStatus(Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"

@dataclass
class MarketData:
    symbol: str
    current_price: float
    volatility: float
    volume_24h: float
    bid_depth: float
    ask_depth: float
    spread: float
    
    def to_dict(self):
        return asdict(self)

@dataclass
class BalanceInfo:
    currency: str
    balance: float
    usd_value: float
    market_symbol: str

@dataclass
class PriorityScore:
    currency: str
    balance: float
    usd_value: float
    priority_score: float
    market_data: MarketData

@dataclass
class TradingDecision:
    strategy: SellStrategy
    parameters: Dict[str, Any]
    reasoning: str
    confidence: float

# Улучшенный Rate Limiter для Cerebras
class RateLimiter:
    def __init__(self, requests_per_min=30, tokens_per_min=60000):
        self.requests_per_min = requests_per_min
        self.tokens_per_min = tokens_per_min
        self.request_times = deque()
        self.token_usage = deque()
        self.lock = Lock()
    
    def can_make_request(self, estimated_tokens=1000):
        with self.lock:
            now = time.time()
            minute_ago = now - 60
            
            # Очищаем старые записи
            while self.request_times and self.request_times[0] < minute_ago:
                self.request_times.popleft()
            
            while self.token_usage and self.token_usage[0][0] < minute_ago:
                self.token_usage.popleft()
            
            # Проверяем лимиты
            current_requests = len(self.request_times)
            current_tokens = sum(usage[1] for usage in self.token_usage)
            
            return (current_requests < self.requests_per_min and 
                    current_tokens + estimated_tokens < self.tokens_per_min)
    
    def record_usage(self, tokens_used):
        with self.lock:
            now = time.time()
            self.request_times.append(now)
            self.token_usage.append((now, tokens_used))

# Настройки для Cerebras API
CEREBRAS_MODEL = "qwen-3-235b-a22b-thinking-2507"
cerebras_limiter = RateLimiter()

# --- УПРАВЛЕНИЕ БАЗОЙ ДАННЫХ ---
class DatabaseManager:
    def __init__(self, supabase_client: Client):
        if not supabase_client:
            raise ValueError("Supabase client is required")
        self.supabase = supabase_client
        self.lock = Lock()
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных в Supabase"""
        try:
            # Создание таблицы для хранения исторических данных о ценах
            self.supabase.table('safetrade_price_history').select('*').limit(1).execute()
            logging.info("Таблица safetrade_price_history доступна")
            
            # Создание таблицы для хранения истории ордеров
            self.supabase.table('safetrade_order_history').select('*').limit(1).execute()
            logging.info("Таблица safetrade_order_history доступна")
            
            # Создание таблицы для хранения решений ИИ
            self.supabase.table('safetrade_ai_decisions').select('*').limit(1).execute()
            logging.info("Таблица safetrade_ai_decisions доступна")
            
            # Создание таблицы для хранения торговых пар
            self.supabase.table('safetrade_trading_pairs').select('*').limit(1).execute()
            logging.info("Таблица safetrade_trading_pairs доступна")
            
            # Создание таблицы для метрик производительности
            self.supabase.table('safetrade_performance_metrics').select('*').limit(1).execute()
            logging.info("Таблица safetrade_performance_metrics доступна")
            
        except Exception as e:
            logging.error(f"Ошибка инициализации базы данных: {e}")
            raise
    
    def insert_price_history(self, timestamp: str, symbol: str, price: float, 
                           volume: float = None, high: float = None, low: float = None):
        """Вставка исторических данных о ценах"""
        try:
            data = {
                'timestamp': timestamp,
                'symbol': symbol,
                'price': price,
                'volume': volume,
                'high': high,
                'low': low,
                'created_at': datetime.now().isoformat()
            }
            result = self.supabase.table('safetrade_price_history').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Ошибка вставки данных о ценах: {e}")
            return None
    
    def insert_order_history(self, order_id: str, timestamp: str, symbol: str, 
                           side: str, order_type: str, amount: float, 
                           price: float = None, total: float = None, status: str = "pending"):
        """Вставка истории ордеров"""
        try:
            data = {
                'order_id': order_id,
                'timestamp': timestamp,
                'symbol': symbol,
                'side': side,
                'order_type': order_type,
                'amount': amount,
                'price': price,
                'total': total,
                'status': status,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            result = self.supabase.table('safetrade_order_history').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Ошибка вставки истории ордеров: {e}")
            return None
    
    def update_order_status(self, order_id: str, status: str):
        """Обновление статуса ордера"""
        try:
            data = {
                'status': status,
                'updated_at': datetime.now().isoformat()
            }
            result = self.supabase.table('safetrade_order_history').update(data).eq('order_id', order_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Ошибка обновления статуса ордера: {e}")
            return None
    
    def insert_ai_decision(self, timestamp: str, decision_type: str, decision_data: str,
                          market_data: str = None, reasoning: str = None, confidence: float = None):
        """Вставка решений ИИ"""
        try:
            data = {
                'timestamp': timestamp,
                'decision_type': decision_type,
                'decision_data': decision_data,
                'market_data': market_data,
                'reasoning': reasoning,
                'confidence': confidence,
                'created_at': datetime.now().isoformat()
            }
            result = self.supabase.table('safetrade_ai_decisions').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Ошибка вставки решения ИИ: {e}")
            return None
    
    def insert_trading_pair(self, symbol: str, base_currency: str, quote_currency: str, is_active: bool = True):
        """Вставка торговой пары"""
        try:
            data = {
                'symbol': symbol,
                'base_currency': base_currency,
                'quote_currency': quote_currency,
                'is_active': is_active,
                'last_updated': datetime.now().isoformat(),
                'created_at': datetime.now().isoformat()
            }
            result = self.supabase.table('safetrade_trading_pairs').upsert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Ошибка вставки торговой пары: {e}")
            return None
    
    def insert_performance_metric(self, timestamp: str, metric_type: str, metric_name: str, 
                                value: float, metadata: str = None):
        """Вставка метрики производительности"""
        try:
            data = {
                'timestamp': timestamp,
                'metric_type': metric_type,
                'metric_name': metric_name,
                'value': value,
                'metadata': metadata,
                'created_at': datetime.now().isoformat()
            }
            result = self.supabase.table('safetrade_performance_metrics').insert(data).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logging.error(f"Ошибка вставки метрики: {e}")
            return None
    
    def get_ai_decisions(self, limit: int = 10):
        """Получение последних решений ИИ"""
        try:
            result = self.supabase.table('safetrade_ai_decisions').select('*').order('created_at', desc=True).limit(limit).execute()
            return result.data
        except Exception as e:
            logging.error(f"Ошибка получения решений ИИ: {e}")
            return []

# Инициализация менеджера базы данных
db_manager = DatabaseManager(supabase)

# --- УЛУЧШЕННЫЙ TELEGRAM BOT С RETRY МЕХАНИЗМОМ ---
class RobustTeleBot(telebot.TeleBot):
    def __init__(self, token, **kwargs):
        super().__init__(token, **kwargs)
        
    def infinity_polling_with_retry(self, timeout=20, long_polling_timeout=20, 
                                   retry_attempts=5, retry_delay=30):
        """Infinity polling с улучшенной обработкой ошибок"""
        attempt = 0
        while attempt < retry_attempts:
            try:
                logging.info(f"Запуск infinity polling (попытка {attempt + 1}/{retry_attempts})")
                self.infinity_polling(timeout=timeout, long_polling_timeout=long_polling_timeout)
                break
            except requests.exceptions.ConnectionError as e:
                attempt += 1
                if "api.telegram.org" in str(e):
                    logging.error(f"DNS/Connection ошибка (попытка {attempt}): {e}")
                    if attempt < retry_attempts:
                        logging.info(f"Повтор через {retry_delay} секунд...")
                        time.sleep(retry_delay)
                        # Увеличиваем задержку экспоненциально
                        retry_delay *= 2
                    else:
                        logging.error("Исчерпаны все попытки подключения")
                        raise
                else:
                    raise
            except Exception as e:
                logging.error(f"Неожиданная ошибка: {e}")
                raise

# --- ИНИЦИАЛИЗАЦИЯ ---
scraper = cloudscraper.create_scraper()

# Инициализируем бота только если есть токен
bot = None
if TELEGRAM_BOT_TOKEN:
    bot = RobustTeleBot(TELEGRAM_BOT_TOKEN)
else:
    logging.warning("SAFETRADE_TELEGRAM_BOT_TOKEN не указан. Telegram бот будет отключен.")

# Инициализируем Supabase (обязательно)
if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("❌ Supabase настройки обязательны!")
    logging.error("   - SAFETRADE_SUPABASE_URL")
    logging.error("   - SAFETRADE_SUPABASE_KEY")
    logging.error("Бот не может работать без Supabase")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logging.info("✅ Supabase подключен")

# Инициализируем Cerebras только если есть API ключ
cerebras_client = None
if CEREBRAS_API_KEY:
    cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)
    logging.info("Cerebras AI подключен")
else:
    logging.info("Cerebras AI не настроен - функции ИИ отключены")

# Настраиваем клавиатуру с командами
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_all')
menu_markup.row('/history', '/ai_status')
menu_markup.row('/markets', '/config')
menu_markup.row('/donate', '/help')
menu_markup.row('/health', '/restart')

# --- WEBHOOK MODE AS FALLBACK ---
def setup_webhook_mode():
    """Настройка webhook режима как альтернативы polling"""
    webhook_url = os.getenv("SAFETRADE_WEBHOOK_URL")  # SAFETRADE_WEBHOOK_URL в переменных окружения
    webhook_port = int(os.getenv("SAFETRADE_WEBHOOK_PORT", "8443"))
    
    if webhook_url:
        try:
            bot.remove_webhook()
            bot.set_webhook(url=webhook_url)
            logging.info(f"Webhook настроен: {webhook_url}")
            
            from flask import Flask, request
            app = Flask(__name__)
            
            @app.route('/' + TELEGRAM_BOT_TOKEN, methods=['POST'])
            def webhook():
                json_str = request.get_data().decode('UTF-8')
                update = telebot.types.Update.de_json(json_str)
                bot.process_new_updates([update])
                return ''
            
            app.run(host='0.0.0.0', port=webhook_port)
            return True
        except Exception as e:
            logging.error(f"Ошибка настройки webhook: {e}")
            return False
    return False

# --- Graceful shutdown ---
def shutdown_handler(signum, frame):
    logging.info("Завершение бота...")
    try:
        # Отменяем все активные ордера
        cancel_all_active_orders()
        # Сохраняем состояние кэша
        save_cache_state()
    except Exception as e:
        logging.error(f"Ошибка при завершении: {e}")
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# --- ВАЛИДАЦИЯ ПАРАМЕТРОВ ---
class OrderValidator:
    @staticmethod
    def validate_order_params(symbol, amount, order_type="market", price=None):
        """Валидация параметров ордера"""
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Symbol должен быть строкой")
        
        if amount <= 0:
            raise ValueError("Amount должен быть положительным числом")
        
        if order_type not in ["market", "limit"]:
            raise ValueError("Order type должен быть 'market' или 'limit'")
        
        if order_type == "limit":
            if price is None or price <= 0:
                raise ValueError("Для limit ордера price должен быть положительным")
        
        # Проверяем минимальный размер ордера
        if amount * (price or 1) < MIN_POSITION_VALUE_USD:
            raise ValueError(f"Размер ордера меньше минимального ({MIN_POSITION_VALUE_USD} USD)")
        
        return True
    
    @staticmethod
    def validate_market_conditions(market_data: MarketData):
        """Валидация рыночных условий"""
        if market_data.spread > CONFIG['risk_management']['max_spread_threshold']:
            logging.warning(f"Высокий спред для {market_data.symbol}: {market_data.spread:.4f}")
        
        if market_data.volatility > CONFIG['risk_management']['max_volatility_threshold']:
            logging.warning(f"Высокая волатильность для {market_data.symbol}: {market_data.volatility:.4f}")
        
        if market_data.volume_24h < 1000:  # Минимальный объем торгов
            logging.warning(f"Низкий объем торгов для {market_data.symbol}: {market_data.volume_24h}")
        
        return True

order_validator = OrderValidator()

# --- Функции для работы с API SafeTrade ---
def generate_signature(nonce, key, secret_bytes):
    """Генерирует подпись HMAC-SHA256"""
    string_to_sign = nonce + key
    return hmac.new(secret_bytes, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

def get_auth_headers():
    """Собирает все заголовки для аутентификации"""
    nonce = str(int(time.time() * 1000))
    signature = generate_signature(nonce, API_KEY, API_SECRET_BYTES)
    return {
        'X-Auth-Apikey': API_KEY,
        'X-Auth-Nonce': nonce,
        'X-Auth-Signature': signature,
        'Content-Type': 'application/json'
    }

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_all_markets():
    """Получает все доступные торговые пары с биржи"""
    global markets_cache
    
    with cache_lock:
        if (markets_cache["data"] and 
            markets_cache["last_update"] and 
            time.time() - markets_cache["last_update"] < markets_cache["cache_duration"]):
            return markets_cache["data"]
    
    try:
        path = "/public/markets"
        url = BASE_URL + path
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        markets = response.json()
        
        if isinstance(markets, list):
            # Фильтруем только пары с USDT
            usdt_markets = [
                market for market in markets 
                if market.get('quote_unit') == 'usdt' and 
                   market.get('base_unit', '').upper() not in EXCLUDED_CURRENCIES
            ]
            
            with cache_lock:
                markets_cache["data"] = usdt_markets
                markets_cache["last_update"] = time.time()
            
            # Сохраняем в базу данных
            save_markets_to_db(usdt_markets)
            
            return usdt_markets
    except Exception as e:
        logging.error(f"Ошибка при получении торговых пар: {e}")
        # В случае ошибки, пробуем получить из базы данных
        return get_markets_from_db()
    
    return []

def save_markets_to_db(markets):
    """Сохраняет торговые пары в базу данных"""
    try:
        for market in markets:
            db_manager.insert_trading_pair(
                symbol=market.get('id', ''),
                base_currency=market.get('base_unit', ''),
                quote_currency=market.get('quote_currency', ''),
                is_active=True
            )
        logging.info(f"Сохранено {len(markets)} торговых пар в Supabase")
    except Exception as e:
        logging.error(f"Ошибка при сохранении торговых пар: {e}")

def get_markets_from_db():
    """Получает торговые пары из базы данных"""
    try:
        result = db_manager.supabase.table('safetrade_trading_pairs').select('*').eq('is_active', True).execute()
        
        markets = []
        for row in result.data:
            markets.append({
                'id': row['symbol'],
                'base_unit': row['base_currency'],
                'quote_unit': row['quote_currency'],
                'active': row['is_active']
            })
        
        return markets
    except Exception as e:
        logging.error(f"Ошибка при получении торговых пар из БД: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_sellable_balances():
    """Получает балансы всех криптовалют кроме USDT"""
    try:
        path = "/trade/account/balances/spot"
        url = BASE_URL + path
        headers = get_auth_headers()
        response = scraper.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        balances = response.json()
        
        if not isinstance(balances, list):
            logging.warning("Некорректный формат балансов")
            return None
        
        # Получаем доступные торговые пары
        markets = get_all_markets()
        available_currencies = {market.get('base_unit', '').upper() for market in markets}
        
        sellable_balances = {}
        for balance in balances:
            currency = balance.get('currency', '').upper()
            balance_amount = float(balance.get('balance', 0))
            
            # Пропускаем исключенные валюты и нулевые балансы
            if (currency in EXCLUDED_CURRENCIES or 
                balance_amount <= 0 or
                currency not in available_currencies):
                continue
            
            sellable_balances[currency] = balance_amount
        
        if sellable_balances:
            logging.info(f"Найдены продаваемые балансы: {sellable_balances}")
            return sellable_balances
        
        return None
    except Exception as e:
        logging.error(f"Ошибка при получении балансов: {e}")
        return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_ticker_price(symbol):
    """Получает текущую цену для указанной торговой пары"""
    global prices_cache
    
    with cache_lock:
        if (symbol in prices_cache["data"] and 
            prices_cache["last_update"] and 
            time.time() - prices_cache["last_update"] < prices_cache["cache_duration"]):
            return prices_cache["data"][symbol]
    
    try:
        path = f"/public/markets/{symbol}/tickers"
        url = BASE_URL + path
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        ticker = response.json()
        
        if not isinstance(ticker, dict):
            logging.warning(f"Некорректный формат тикера для {symbol}")
            return None
        
        price = float(ticker.get('last', 0))
        
        with cache_lock:
            prices_cache["data"][symbol] = price
            prices_cache["last_update"] = time.time()
        
        # Сохраняем в базу данных
        db_manager.insert_price_history(
            symbol=symbol.upper(),
            price=price,
            volume=float(ticker.get('vol', 0)) if ticker.get('vol') else None,
            high=float(ticker.get('high', 0)) if ticker.get('high') else None,
            low=float(ticker.get('low', 0)) if ticker.get('low') else None
        )
        
        return price
    except Exception as e:
        logging.error(f"Ошибка получения цены для {symbol}: {e}")
        return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_orderbook(symbol):
    """Получение книги ордеров для указанной пары"""
    global orderbook_cache
    
    with cache_lock:
        if (symbol in orderbook_cache["data"] and 
            symbol in orderbook_cache["last_update"] and 
            time.time() - orderbook_cache["last_update"][symbol] < orderbook_cache["cache_duration"]):
            return orderbook_cache["data"][symbol]
    
    try:
        path = f"/public/markets/{symbol}/order-book"
        url = BASE_URL + path
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        orderbook = response.json()
        
        if not orderbook or not orderbook.get('bids') or not orderbook.get('asks'):
            logging.warning(f"Пустая книга ордеров для {symbol}")
            return None
        
        with cache_lock:
            orderbook_cache["data"][symbol] = orderbook
            orderbook_cache["last_update"][symbol] = time.time()
        
        return orderbook
    except Exception as e:
        logging.error(f"Ошибка получения книги ордеров для {symbol}: {e}")
        return None

def calculate_volatility(orderbook):
    """Расчет волатильности на основе книги ордеров"""
    if not orderbook or not orderbook.get('bids') or not orderbook.get('asks'):
        logging.warning("Недостаточно данных для расчета волатильности")
        return 0
    
    try:
        best_bid = float(orderbook['bids'][0][0])
        best_ask = float(orderbook['asks'][0][0])
        spread = (best_ask - best_bid) / best_bid
        
        # Анализируем глубину книги ордеров
        bid_depth = sum(float(bid[1]) for bid in orderbook['bids'][:5])
        ask_depth = sum(float(ask[1]) for ask in orderbook['asks'][:5])
        depth_ratio = min(bid_depth, ask_depth) / max(bid_depth, ask_depth) if max(bid_depth, ask_depth) > 0 else 0
        
        # Комбинированный показатель волатильности
        volatility = spread * (1 - depth_ratio)
        return volatility
    except Exception as e:
        logging.error(f"Ошибка при расчете волатильности: {e}")
        return 0

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_market_data(symbol):
    """Получает полные рыночные данные для указанной пары"""
    try:
        # Получаем текущую цену
        current_price = get_ticker_price(symbol)
        if not current_price:
            logging.warning(f"Не удалось получить цену для {symbol}")
            return None
        
        # Получаем книгу ордеров
        orderbook = get_orderbook(symbol)
        if not orderbook:
            logging.warning(f"Не удалось получить книгу ордеров для {symbol}")
            return None
        
        # Рассчитываем метрики
        volatility = calculate_volatility(orderbook)
        
        # Рассчитываем глубину
        bid_depth = sum(float(bid[1]) for bid in orderbook.get('bids', [])[:10])
        ask_depth = sum(float(ask[1]) for ask in orderbook.get('asks', [])[:10])
        
        # Рассчитываем спред
        best_bid = float(orderbook['bids'][0][0]) if orderbook['bids'] else 0
        best_ask = float(orderbook['asks'][0][0]) if orderbook['asks'] else 0
        spread = (best_ask - best_bid) / best_bid if best_bid > 0 else 0
        
        # Получаем объем торгов (из тикера)
        path = f"/public/markets/{symbol}/tickers"
        url = BASE_URL + path
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        ticker = response.json()
        volume_24h = float(ticker.get('vol', 0))
        
        market_data = MarketData(
            symbol=symbol.upper(),
            current_price=current_price,
            volatility=volatility,
            volume_24h=volume_24h,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            spread=spread
        )
        
        # Валидируем рыночные условия
        order_validator.validate_market_conditions(market_data)
        
        return market_data
    except Exception as e:
        logging.error(f"Ошибка при получении рыночных данных для {symbol}: {e}")
        return None

def prioritize_sales(balances_dict):
    """Сортирует валюты по приоритету продажи"""
    priority_scores = []
    
    for currency, balance in balances_dict.items():
        try:
            if balance <= 0:
                continue
            
            # Определяем символ торговой пары
            market_symbol = f"{currency.lower()}usdt"
            
            # Получаем рыночные данные
            market_data = get_market_data(market_symbol)
            if not market_data:
                continue
            
            # Рассчитываем стоимость в USD
            usd_value = balance * market_data.current_price
            
            # Пропускаем, если стоимость ниже минимальной
            if usd_value < MIN_POSITION_VALUE_USD:
                continue
            
            # Рассчитываем приоритетный балл
            weight_value = 0.4
            weight_liquidity = 0.3
            weight_volatility = 0.2
            weight_spread = 0.1
            
            # Нормализуем показатели (0-1)
            value_score = min(usd_value / 1000, 1.0)
            liquidity_score = min(market_data.bid_depth / 10000, 1.0)
            volatility_score = 1 - min(market_data.volatility * 100, 1.0)
            spread_score = 1 - min(market_data.spread * 100, 1.0)
            
            # Итоговый балл
            priority_score = (
                weight_value * value_score +
                weight_liquidity * liquidity_score +
                weight_volatility * volatility_score +
                weight_spread * spread_score
            )
            
            priority_scores.append(PriorityScore(
                currency=currency,
                balance=balance,
                usd_value=usd_value,
                priority_score=priority_score,
                market_data=market_data
            ))
            
        except Exception as e:
            logging.error(f"Ошибка при расчете приоритета для {currency}: {e}")
            continue
    
    # Сортируем по убыванию приоритета
    priority_scores.sort(key=lambda x: x.priority_score, reverse=True)
    
    return priority_scores

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_ai_trading_decision(currency, balance, market_data):
    """Получение решения о торговле от ИИ для конкретной валюты"""
    if not cerebras_client:
        return None
    
    estimated_tokens = 2000
    if not cerebras_limiter.can_make_request(estimated_tokens):
        logging.warning("Достигнут лимит Cerebras API. Используется стандартная стратегия.")
        return None
    
    try:
        # Валидация входных данных
        if balance <= 0 or not market_data:
            logging.warning(f"Некорректные данные для ИИ: balance={balance}, market_data={market_data}")
            return None
        
        # Определяем размер позиции в USD
        usd_value = balance * market_data.current_price
        
        # Выбираем базовую стратегию на основе размера позиции
        if usd_value < 50:
            base_strategy = "market"
        elif usd_value < 500:
            base_strategy = "limit"
        else:
            base_strategy = "twap"
        
        # Формируем контекст для ИИ
        context = f"""
        Ты - торговый ИИ-ассистент для криптовалютной биржи SafeTrade. Твоя задача - проанализировать текущие рыночные условия и предложить оптимальную стратегию для продажи {balance} {currency} за USDT.
        
        Текущие рыночные данные:
        - Баланс {currency}: {balance}
        - Стоимость в USD: ${usd_value:.2f}
        - Текущая цена: {market_data.current_price}
        - Волатильность рынка: {market_data.volatility:.4f}
        - Объем торгов за 24 часа: {market_data.volume_24h}
        - Глубина книги ордеров (покупка): {market_data.bid_depth}
        - Глубина книги ордеров (продажа): {market_data.ask_depth}
        - Спред: {market_data.spread:.4f}
        
        Рекомендуемая базовая стратегия: {base_strategy}
        
        Доступные стратегии:
        1. market - немедленное исполнение по рыночной цене
        2. limit - исполнение по указанной цене или лучше
        3. twap - разделение на части через равные промежутки времени
        4. iceberg - отображение только части ордера
        5. adaptive - динамический выбор на основе рыночных условий
        
        Ответь в формате JSON:
        {{
            "strategy": "market|limit|twap|iceberg|adaptive",
            "parameters": {{
                "price": 0.0,
                "duration_minutes": 60,
                "chunks": 6,
                "visible_amount": 0.1,
                "max_attempts": 20
            }},
            "reasoning": "Обоснование выбора стратегии",
            "confidence": 0.85
        }}
        """
        
        # Отправляем запрос к ИИ
        response = cerebras_client.chat.completions.create(
            messages=[{"role": "user", "content": context}],
            model=CEREBRAS_MODEL,
            max_completion_tokens=4000,
        )
        
        # Парсим ответ
        ai_response = response.choices[0].message.content
        
        # Ищем JSON в ответе
        try:
            start_idx = ai_response.find('{')
            end_idx = ai_response.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                json_str = ai_response[start_idx:end_idx]
                decision = json.loads(json_str)
                
                # Создаем объект решения
                trading_decision = TradingDecision(
                    strategy=SellStrategy(decision.get("strategy", "market")),
                    parameters=decision.get("parameters", {}),
                    reasoning=decision.get("reasoning", ""),
                    confidence=decision.get("confidence", 0.5)
                )
                
                # Сохраняем решение ИИ
                db_manager.insert_ai_decision(
                    timestamp=datetime.now().isoformat(),
                    decision_type="trading_strategy",
                    decision_data=json.dumps(decision),
                    market_data=json.dumps(market_data.to_dict()),
                    reasoning=trading_decision.reasoning,
                    confidence=trading_decision.confidence
                )
                
                # Обновляем использование rate limiter
                input_tokens = len(context) // 4
                output_tokens = len(ai_response) // 4
                cerebras_limiter.record_usage(input_tokens + output_tokens)
                
                return trading_decision
            else:
                logging.error(f"Не удалось найти JSON в ответе ИИ: {ai_response}")
                return None
        except (json.JSONDecodeError, ValueError) as e:
            logging.error(f"Ошибка парсинга JSON из ответа ИИ: {e}")
            return None
    except Exception as e:
        logging.error(f"Ошибка при получении решения от ИИ: {e}")
        return None

def execute_trading_strategy(priority_score: PriorityScore, ai_decision: TradingDecision = None):
    """Исполняет торговую стратегию для конкретной валюты"""
    try:
        market_symbol = f"{priority_score.currency.lower()}usdt"
        amount = priority_score.balance
        
        # Валидируем параметры
        order_validator.validate_order_params(market_symbol, amount)
        
        if ai_decision and ai_decision.strategy:
            strategy = ai_decision.strategy
            parameters = ai_decision.parameters
        else:
            # Используем стандартную логику выбора стратегии
            if priority_score.usd_value < 50:
                strategy = SellStrategy.MARKET
                parameters = {}
            elif priority_score.usd_value < 500:
                strategy = SellStrategy.LIMIT
                # Устанавливаем цену чуть ниже текущей рыночной
                parameters = {"price": priority_score.market_data.current_price * 0.999}
            else:
                strategy = SellStrategy.TWAP
                parameters = {"duration_minutes": 60, "chunks": 6}
        
        logging.info(f"Исполняем стратегию {strategy.value} для {priority_score.currency}")
        
        # Исполняем выбранную стратегию
        if strategy == SellStrategy.MARKET:
            return execute_market_sell(market_symbol, amount)
        elif strategy == SellStrategy.LIMIT:
            price = parameters.get("price", priority_score.market_data.current_price * 0.999)
            return execute_limit_sell(market_symbol, amount, price)
        elif strategy == SellStrategy.TWAP:
            duration = parameters.get("duration_minutes", 60)
            chunks = parameters.get("chunks", 6)
            return execute_twap_sell(market_symbol, amount, duration, chunks)
        elif strategy == SellStrategy.ICEBERG:
            visible_ratio = parameters.get("visible_amount", 0.1)
            max_attempts = parameters.get("max_attempts", 20)
            return execute_iceberg_sell(market_symbol, amount, visible_ratio, max_attempts)
        elif strategy == SellStrategy.ADAPTIVE:
            return execute_adaptive_sell(market_symbol, amount)
        
        return False
    except Exception as e:
        logging.error(f"Ошибка при исполнении стратегии для {priority_score.currency}: {e}")
        return False

def execute_market_sell(market_symbol, amount):
    """Исполнение рыночной продажи"""
    try:
        result = create_sell_order_safetrade(market_symbol, amount, "market")
        return "✅" in result
    except Exception as e:
        logging.error(f"Ошибка рыночной продажи {market_symbol}: {e}")
        return False

def execute_limit_sell(market_symbol, amount, price):
    """Исполнение лимитной продажи"""
    try:
        result = create_sell_order_safetrade(market_symbol, amount, "limit", price)
        return "✅" in result
    except Exception as e:
        logging.error(f"Ошибка лимитной продажи {market_symbol}: {e}")
        return False

def execute_twap_sell(market_symbol, total_amount, duration_minutes=60, chunks=6):
    """Исполнение TWAP продажи"""
    if total_amount <= 0 or chunks <= 0:
        logging.warning("Некорректные параметры для TWAP")
        return False
    
    chunk_amount = total_amount / chunks
    interval_seconds = (duration_minutes * 60) / chunks
    successful_chunks = 0
    
    for i in range(chunks):
        try:
            # Получаем текущую цену
            current_price = get_ticker_price(market_symbol)
            if not current_price:
                continue
            
            # Размещаем лимитный ордер чуть выше текущей цены
            limit_price = current_price * 1.001
            result = create_sell_order_safetrade(market_symbol, chunk_amount, "limit", limit_price)
            
            if "✅" in result:
                successful_chunks += 1
                order_id = extract_order_id_from_result(result)
                if order_id:
                    # Отслеживаем исполнение ордера
                    threading.Thread(target=track_order_execution, args=(order_id, 300)).start()
            
            # Ждем до следующего интервала
            if i < chunks - 1:
                time.sleep(interval_seconds)
        except Exception as e:
            logging.error(f"Ошибка в TWAP исполнении чанка {i + 1}: {e}")
    
    return successful_chunks > 0

def execute_iceberg_sell(market_symbol, total_amount, visible_ratio=0.1, max_attempts=20):
    """Исполнение Iceberg продажи"""
    if total_amount <= 0 or visible_ratio <= 0 or max_attempts <= 0:
        logging.warning("Некорректные параметры для Iceberg")
        return False
    
    remaining = total_amount
    attempts = 0
    successful_orders = 0
    
    while remaining > 0 and attempts < max_attempts:
        try:
            # Определяем размер видимой части
            current_visible = min(visible_ratio * total_amount, remaining)
            
            # Получаем лучшую цену покупки из книги ордеров
            orderbook = get_orderbook(market_symbol)
            if not orderbook or not orderbook.get('bids'):
                attempts += 1
                time.sleep(5)
                continue
            
            best_bid = float(orderbook['bids'][0][0])
            
            # Размещаем лимитный ордер
            result = create_sell_order_safetrade(market_symbol, current_visible, "limit", best_bid)
            
            if "✅" in result:
                successful_orders += 1
                remaining -= current_visible
                order_id = extract_order_id_from_result(result)
                if order_id:
                    threading.Thread(target=track_order_execution, args=(order_id, 60)).start()
            
            attempts += 1
            time.sleep(5)
        except Exception as e:
            logging.error(f"Ошибка в Iceberg исполнении: {e}")
            attempts += 1
    
    return successful_orders > 0

def execute_adaptive_sell(market_symbol, total_amount):
    """Адаптивная продажа на основе книги ордеров"""
    if total_amount <= 0:
        logging.warning("Некорректный amount для adaptive")
        return False
    
    try:
        orderbook = get_orderbook(market_symbol)
        if not orderbook or not orderbook.get('bids'):
            logging.warning(f"Пустая книга ордеров для {market_symbol}")
            return False
        
        # Анализируем ликвидность на разных уровнях
        bids = orderbook.get('bids', [])
        price_levels = {}
        for bid in bids[:CONFIG['trading']['strategies']['adaptive']['max_price_levels']]:
            price = float(bid[0])
            amount = float(bid[1])
            price_levels[price] = price_levels.get(price, 0) + amount
        
        # Сортируем по цене (от высокой к низкой)
        sorted_prices = sorted(price_levels.keys(), reverse=True)
        
        # Размещаем ордера на разных уровнях
        remaining = total_amount
        placed_orders = 0
        liquidity_ratio = CONFIG['trading']['strategies']['adaptive']['liquidity_ratio']
        
        for price in sorted_prices:
            if remaining <= 0:
                break
                
            liquidity_at_price = price_levels[price]
            order_size = min(remaining, liquidity_at_price * liquidity_ratio)
            
            if order_size > 0:
                result = create_sell_order_safetrade(market_symbol, order_size, "limit", price)
                if "✅" in result:
                    placed_orders += 1
                    remaining -= order_size
                    order_id = extract_order_id_from_result(result)
                    if order_id:
                        threading.Thread(target=track_order_execution, args=(order_id, 600)).start()
        
        # Если остались неразмещенные средства, используем рыночный ордер
        if remaining > 0:
            result = create_sell_order_safetrade(market_symbol, remaining, "market")
            if "✅" in result:
                placed_orders += 1
        
        return placed_orders > 0
    except Exception as e:
        logging.error(f"Ошибка в adaptive продаже {market_symbol}: {e}")
        return False

def extract_order_id_from_result(result_text):
    """Извлекает ID ордера из результата создания ордера"""
    try:
        if "ID ордера:" in result_text:
            return result_text.split('ID ордера: ')[-1].split('\n')[0].strip('`')
    except:
        pass
    return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def create_sell_order_safetrade(market_symbol, amount, order_type="market", price=None):
    """Создает ордер на продажу и возвращает отформатированный результат"""
    try:
        # Валидация параметров
        order_validator.validate_order_params(market_symbol, amount, order_type, price)
        
        path = "/trade/market/orders"
        url = BASE_URL + path
        
        # Определяем валюты из символа
        base_currency = market_symbol.replace('usdt', '').upper()
        
        payload = {
            "market": market_symbol,
            "side": "sell",
            "type": order_type,
            "amount": str(amount)
        }
        
        if order_type == "limit" and price:
            payload["price"] = str(price)
        
        headers = get_auth_headers()
        response = scraper.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        order_details = response.json()
        
        order_id = order_details.get('id')
        order_amount = order_details.get('amount', amount)
        
        # Сохраняем данные об ордере в локальную базу
        db_manager.insert_order_history(
            order_id=order_id,
            timestamp=datetime.now().isoformat(),
            symbol=order_details.get('market', 'N/A'),
            side=order_details.get('side', 'N/A'),
            order_type=order_details.get('type', 'N/A'),
            amount=float(order_amount),
            price=float(order_details.get('price', 0)) if order_details.get('price') else None,
            total=float(order_details.get('total', 0)) if order_details.get('total') else None,
            status=order_details.get('state', 'N/A')
        )
        
        if order_id:
            threading.Thread(target=track_order, args=(order_id,)).start()
        
        return (
            f"✅ *Успешно размещен ордер на продажу!*\n\n"
            f"*Биржа:* SafeTrade\n"
            f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
            f"*Тип:* `{order_details.get('type', 'N/A').capitalize()}`\n"
            f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
            f"*Заявленный объем:* `{order_amount} {base_currency}`\n"
            f"*ID ордера:* `{order_id}`"
        )
    except Exception as e:
        error_message = f"❌ Ошибка при создании ордера на продажу на SafeTrade: {e}"
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_details = e.response.text
                error_message += f"\nОтвет сервера: `{error_details}`"
            except:
                pass
        logging.error(error_message)
        return error_message

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def track_order_execution(order_id, timeout=300):
    """Отслеживает исполнение ордера и возвращает trades"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            path = f"/trade/market/orders/{order_id}/trades"
            url = BASE_URL + path
            response = scraper.get(url, headers=get_auth_headers(), timeout=30)
            response.raise_for_status()
            trades = response.json()
            if trades:
                # Обновляем статус ордера в базе данных
                total_executed = sum(float(t.get('total', 0)) for t in trades)
                db_manager.update_order_status(
                    order_id=order_id,
                    status="filled"
                )
                return trades
            time.sleep(10)
        except Exception as e:
            logging.error(f"Ошибка отслеживания ордера {order_id}: {e}")
            time.sleep(10)
    
    logging.warning(f"Таймаут отслеживания ордера {order_id}")
    return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def cancel_order(order_id):
    """Отменяет ордер"""
    try:
        path = f"/trade/market/orders/{order_id}/cancel"
        url = BASE_URL + path
        response = scraper.post(url, headers=get_auth_headers(), timeout=30)
        response.raise_for_status()
        logging.info(f"Ордер {order_id} отменён")
        
        # Обновляем статус в базе данных
        db_manager.update_order_status(
            order_id=order_id,
            status="cancelled"
        )
        return True
    except Exception as e:
        logging.error(f"Ошибка отмены ордера {order_id}: {e}")
        return False

def track_order(order_id):
    """Фоновая функция для отслеживания ордера"""
    logging.info(f"Отслеживание ордера {order_id} начато")
    try:
        trades = track_order_execution(order_id, timeout=3600)  # 1 час
        if trades:
            logging.info(f"Ордер {order_id} исполнен: {len(trades)} сделок")
        else:
            logging.warning(f"Ордер {order_id} не исполнен в течение часа")
            # Попробуем отменить неисполненный ордер
            cancel_order(order_id)
    except Exception as e:
        logging.error(f"Ошибка отслеживания ордера {order_id}: {e}")

def cancel_all_active_orders():
    """Отменяет все активные ордера при завершении работы"""
    try:
        path = "/trade/market/orders"
        url = BASE_URL + path
        response = scraper.get(url, headers=get_auth_headers(), timeout=30)
        response.raise_for_status()
        orders = response.json()
        
        for order in orders:
            if order.get('state') in ['wait', 'pending']:
                cancel_order(order.get('id'))
        
        logging.info("Все активные ордера отменены")
    except Exception as e:
        logging.error(f"Ошибка отмены активных ордеров: {e}")

def save_cache_state():
    """Сохраняет состояние кэша при завершении работы"""
    try:
        cache_state = {
            "markets": markets_cache,
            "prices": prices_cache,
            "timestamp": time.time()
        }
        with open("cache_state.json", "w") as f:
            json.dump(cache_state, f, default=str)
        logging.info("Состояние кэша сохранено")
    except Exception as e:
        logging.error(f"Ошибка сохранения состояния кэша: {e}")

def load_cache_state():
    """Загружает состояние кэша при запуске"""
    try:
        cache_file = Path("cache_state.json")
        if cache_file.exists():
            with open(cache_file, "r") as f:
                cache_state = json.load(f)
            
            # Проверяем, не устарел ли кэш
            if time.time() - cache_state.get("timestamp", 0) < 3600:  # 1 час
                global markets_cache, prices_cache
                markets_cache.update(cache_state.get("markets", {}))
                prices_cache.update(cache_state.get("prices", {}))
                logging.info("Состояние кэша загружено")
    except Exception as e:
        logging.error(f"Ошибка загрузки состояния кэша: {e}")

def invalidate_cache():
    """Инвалидация кэша после продажи"""
    with cache_lock:
        prices_cache["data"] = {}
        prices_cache["last_update"] = None
        orderbook_cache["data"] = {}
        orderbook_cache["last_update"] = {}
        logging.info("Кэш инвалидирован после операций")

def auto_sell_all_altcoins():
    """
    Главная функция автоматической продажи всех альткоинов
    """
    logging.info("Запуск автоматической продажи всех альткоинов")
    
    try:
        with sales_sem:  # Ограничиваем количество одновременных продаж
            # Получаем все продаваемые балансы
            balances = get_sellable_balances()
            if not balances:
                logging.info("Нет балансов для продажи")
                return {"success": False, "message": "Нет балансов для продажи"}
            
            # Определяем приоритет продаж
            priority_scores = prioritize_sales(balances)
            if not priority_scores:
                logging.info("Нет валют, подходящих для продажи")
                return {"success": False, "message": "Нет валют, подходящих для продажи"}
            
            total_processed = 0
            successful_sales = 0
            failed_sales = 0
            
            # Обрабатываем каждую валюту по приоритету
            for score in priority_scores:
                try:
                    logging.info(f"Обработка {score.currency}: {score.balance} (${score.usd_value:.2f})")
                    
                    # Получаем решение ИИ для оптимальной стратегии
                    ai_decision = None
                    if cerebras_client:
                        ai_decision = get_ai_trading_decision(
                            score.currency, 
                            score.balance, 
                            score.market_data
                        )
                    
                    # Исполняем торговую стратегию
                    success = execute_trading_strategy(score, ai_decision)
                    
                    if success:
                        successful_sales += 1
                        logging.info(f"✅ Успешно продан {score.currency}")
                    else:
                        failed_sales += 1
                        logging.warning(f"❌ Не удалось продать {score.currency}")
                    
                    total_processed += 1
                    
                    # Небольшая задержка между продажами
                    time.sleep(2)
                    
                except Exception as e:
                    logging.error(f"Ошибка при продаже {score.currency}: {e}")
                    failed_sales += 1
                    total_processed += 1
            
            # Инвалидируем кэш после всех операций
            invalidate_cache()
            
            # Отправляем отчет администратору (если бот настроен)
            if bot and ADMIN_CHAT_ID:
                report = (
                    f"🤖 **Отчет по автопродажам**\n\n"
                    f"📊 **Статистика:**\n"
                    f"• Обработано валют: {total_processed}\n"
                    f"• Успешных продаж: {successful_sales}\n"
                    f"• Неудачных попыток: {failed_sales}\n"
                    f"• Время выполнения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"💰 **Обработанные валюты:**\n"
                )
                
                for score in priority_scores[:5]:  # Показываем только топ-5
                    status = "✅" if score.currency in [s.currency for s in priority_scores] else "❌"
                    report += f"{status} {score.currency}: ${score.usd_value:.2f}\n"
                
                try:
                    bot.send_message(
                        ADMIN_CHAT_ID, 
                        report, 
                        parse_mode='Markdown'
                    )
                    logging.info("📱 Отчет отправлен администратору")
                except Exception as e:
                    logging.error(f"Ошибка отправки отчета админу: {e}")
            else:
                logging.info("📊 Отчет по автопродажам:")
                logging.info(f"   Обработано валют: {total_processed}")
                logging.info(f"   Успешных продаж: {successful_sales}")
                logging.info(f"   Неудачных попыток: {failed_sales}")
            
            return {
                "success": True,
                "total_processed": total_processed,
                "successful_sales": successful_sales,
                "failed_sales": failed_sales,
                "message": f"Обработано {total_processed} валют, успешно продано {successful_sales}"
            }
    
    except Exception as e:
        error_msg = f"Критическая ошибка в автопродаже: {e}"
        logging.error(error_msg)
        
        # Отправляем уведомление об ошибке администратору (если бот настроен)
        if bot and ADMIN_CHAT_ID:
            try:
                bot.send_message(
                    ADMIN_CHAT_ID,
                    f"🚨 **Ошибка автопродажи**\n\n{error_msg}",
                    parse_mode='Markdown'
                )
                logging.info("📱 Уведомление об ошибке отправлено администратору")
            except Exception as e:
                logging.error(f"Ошибка отправки уведомления об ошибке: {e}")
        else:
            logging.error(f"🚨 Критическая ошибка в автопродаже: {error_msg}")
        
        return {"success": False, "message": error_msg}

def start_auto_sell_scheduler():
    """Запускает планировщик автоматических продаж"""
    def scheduler():
        while True:
            try:
                time.sleep(AUTO_SELL_INTERVAL)
                auto_sell_all_altcoins()
            except Exception as e:
                logging.error(f"Ошибка в планировщике автопродаж: {e}")
                time.sleep(60)  # Ждем минуту при ошибке
    
    scheduler_thread = threading.Thread(target=scheduler, daemon=True)
    scheduler_thread.start()
    logging.info(f"Планировщик автопродаж запущен с интервалом {AUTO_SELL_INTERVAL} секунд")

# --- TELEGRAM BOT HANDLERS ---
# Проверяем, что бот инициализирован перед регистрацией обработчиков
if bot:
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        """Приветственное сообщение"""
        welcome_text = """
🤖 **Добро пожаловать в SafeTrade Trading Bot!**
Этот бот поможет вам автоматизировать торговлю криптовалютами на бирже SafeTrade.
**Доступные команды:**
• `/balance` - показать текущие балансы
• `/sell_all` - продать все альткоины за USDT
• `/history` - показать историю сделок
• `/ai_status` - статус ИИ-помощника
• `/markets` - показать доступные торговые пары
• `/config` - показать текущую конфигурацию
• `/health` - проверить состояние бота
• `/restart` - перезапустить бота (админ)
• `/donate` - поддержать разработчика
• `/help` - показать эту справку
**Возможности:**
🎯 Умная приоритизация продаж
🧠 ИИ-помощник для выбора стратегий
📊 Несколько торговых стратегий
🔄 Автоматическая торговля
📈 Детальная аналитика
Для начала работы используйте команду `/balance`
"""
        
        bot.reply_to(message, welcome_text, parse_mode='Markdown', reply_markup=menu_markup)

    @bot.message_handler(commands=['health'])
    def health_check(message):
        """Проверка состояния бота"""
        if str(message.chat.id) == ADMIN_CHAT_ID:
            network_status = "✅ OK" if check_network_connectivity() else "❌ Error"
            bot.reply_to(message, f"🤖 Бот: Активен\n🌐 Сеть: {network_status}")
        else:
            bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды")

    @bot.message_handler(commands=['restart'])
    def restart_bot(message):
        """Перезапуск бота"""
        if str(message.chat.id) == ADMIN_CHAT_ID:
            bot.reply_to(message, "🔄 Перезапуск бота...")
            logging.info("Перезапуск бота по команде администратора")
            # Используем graceful shutdown
            shutdown_handler(signal.SIGINT, None)
        else:
            bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды")

    @bot.message_handler(commands=['balance'])
    def show_balance(message):
        """Показывает текущие балансы"""
        try:
            balances = get_sellable_balances()
            if not balances:
                bot.reply_to(message, "❌ Нет балансов для отображения или ошибка получения данных")
                return
            
            priority_scores = prioritize_sales(balances)
            
            response = "💰 **Ваши балансы:**\n\n"
            total_usd = 0
            
            for i, score in enumerate(priority_scores, 1):
                total_usd += score.usd_value
                response += (
                    f"{i}. **{score.currency}**\n"
                    f"   • Количество: `{score.balance:.8f}`\n"
                    f"   • Цена: `${score.market_data.current_price:.6f}`\n"
                    f"   • Стоимость: `${score.usd_value:.2f}`\n"
                    f"   • Приоритет: `{score.priority_score:.3f}`\n"
                    f"   • Волатильность: `{score.market_data.volatility:.4f}`\n\n"
                )
            
            response += f"💵 **Общая стоимость: ${total_usd:.2f}`**"
            
            bot.reply_to(message, response, parse_mode='Markdown')
        
        except Exception as e:
            logging.error(f"Ошибка в show_balance: {e}")
            bot.reply_to(message, f"❌ Ошибка получения балансов: {e}")

    @bot.message_handler(commands=['sell_all'])
    def sell_all_altcoins(message):
        """Продает все альткоины"""
        try:
            # Проверяем права доступа
            if str(message.chat.id) != ADMIN_CHAT_ID:
                bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды")
                return
            
            bot.reply_to(message, "🔄 Начинаю автоматическую продажу всех альткоинов...")
            
            # Запускаем продажу в отдельном потоке
            def sell_thread():
                result = auto_sell_all_altcoins()
                
                if result["success"]:
                    response = (
                        f"✅ **Автопродажа завершена!**\n\n"
                        f"📊 **Результаты:**\n"
                        f"• Обработано: {result['total_processed']}\n"
                        f"• Успешно: {result['successful_sales']}\n"
                        f"• Ошибки: {result['failed_sales']}\n"
                    )
                else:
                    response = f"❌ **Ошибка автопродажи:**\n{result['message']}"
                
                bot.send_message(message.chat.id, response, parse_mode='Markdown')
            
            threading.Thread(target=sell_thread).start()
        
        except Exception as e:
            logging.error(f"Ошибка в sell_all_altcoins: {e}")
            bot.reply_to(message, f"❌ Ошибка запуска автопродажи: {e}")

    @bot.message_handler(commands=['history'])
    def show_history(message):
        """Показывает историю последних сделок"""
        try:
            result = db_manager.supabase.table('safetrade_order_history').select('*').order('created_at', desc=True).limit(10).execute()
            
            orders = result.data
            
            if not orders:
                bot.reply_to(message, "📊 История сделок пуста")
                return
            
            response = "📈 **История последних сделок:**\n\n"
            
            for order in orders:
                order_id = order['order_id']
                timestamp = order['timestamp']
                symbol = order['symbol']
                side = order['side']
                order_type = order['order_type']
                amount = order['amount']
                price = order['price']
                total = order['total']
                status = order['status']
                
                dt = datetime.fromisoformat(timestamp).strftime('%d.%m.%Y %H:%M')
                
                status_emoji = {
                    'filled': '✅',
                    'cancelled': '❌',
                    'pending': '⏳',
                    'partial': '🔄'
                }.get(status.lower(), '❓')
                
                response += (
                    f"{status_emoji} **{symbol.upper()}**\n"
                    f"   • Тип: {order_type.capitalize()} {side.capitalize()}\n"
                    f"   • Количество: `{amount:.8f}`\n"
                    f"   • Цена: `{price:.6f}` (если есть)\n"
                    f"   • Итого: `{total:.6f}` USDT\n"
                    f"   • Время: `{dt}`\n"
                    f"   • ID: `{order_id[:8]}...`\n\n"
                )
            
            bot.reply_to(message, response, parse_mode='Markdown')
        
        except Exception as e:
            logging.error(f"Ошибка в show_history: {e}")
            bot.reply_to(message, f"❌ Ошибка получения истории: {e}")

    @bot.message_handler(commands=['ai_status'])
    def show_ai_status(message):
        """Показывает статус ИИ-помощника"""
        try:
            if not cerebras_client:
                bot.reply_to(message, "❌ ИИ-помощник не настроен (отсутствует CEREBRAS_API_KEY)")
                return
            
            # Получаем последние решения ИИ
            recent_decisions = db_manager.get_ai_decisions(5)
            
            response = "🧠 **Статус ИИ-помощника:**\n\n"
            response += f"✅ **Состояние:** Активен\n"
            
            if recent_decisions:
                response += "📋 **Последние решения:**\n\n"
                
                for decision in recent_decisions:
                    dt = datetime.fromisoformat(decision['timestamp']).strftime('%d.%m %H:%M')
                    confidence = decision['confidence'] or 0
                    confidence_emoji = "🟢" if confidence > 0.7 else "🟡" if confidence > 0.4 else "🔴"
                    
                    try:
                        decision_data = json.loads(decision['decision_data'])
                        strategy = decision_data.get('strategy', 'unknown')
                    except:
                        strategy = 'unknown'
                    
                    response += (
                        f"{confidence_emoji} `{dt}` - **{strategy.upper()}**\n"
                        f"   • Уверенность: `{confidence:.1%}`\n"
                        f"   • Обоснование: _{decision['reasoning'][:50]}..._\n\n"
                    )
            else:
                response += "📋 **Решения:** Пока нет данных\n"
            
            bot.reply_to(message, response, parse_mode='Markdown')
        
        except Exception as e:
            logging.error(f"Ошибка в show_ai_status: {e}")
            bot.reply_to(message, f"❌ Ошибка получения статуса ИИ: {e}")

    @bot.message_handler(commands=['markets'])
    def show_markets(message):
        """Показывает доступные торговые пары"""
        try:
            markets = get_all_markets()
            
            if not markets:
                bot.reply_to(message, "❌ Не удалось получить список торговых пар")
                return
            
            response = f"📊 **Доступные торговые пары ({len(markets)}):**\n\n"
            
            # Показываем первые 20 пар
            for i, market in enumerate(markets[:20], 1):
                symbol = market.get('id', 'N/A').upper()
                base = market.get('base_unit', 'N/A').upper()
                quote = market.get('quote_unit', 'N/A').upper()
                
                response += f"{i}. **{symbol}** ({base}/{quote})\n"
            
            if len(markets) > 20:
                response += f"\n... и еще {len(markets) - 20} пар"
            
            bot.reply_to(message, response, parse_mode='Markdown')
        
        except Exception as e:
            logging.error(f"Ошибка в show_markets: {e}")
            bot.reply_to(message, f"❌ Ошибка получения торговых пар: {e}")

    @bot.message_handler(commands=['config'])
    def show_config(message):
        """Показывает текущую конфигурацию"""
        try:
            response = "⚙️ **Текущая конфигурация:**\n\n"
            
            response += "**🔧 Торговые настройки:**\n"
            response += f"• Исключенные валюты: `{', '.join(EXCLUDED_CURRENCIES)}`\n"
            response += f"• Мин. стоимость позиции: `${MIN_POSITION_VALUE_USD}`\n"
            response += f"• Макс. одновременных продаж: `{MAX_CONCURRENT_SALES}`\n"
            response += f"• Интервал автопродаж: `{AUTO_SELL_INTERVAL}` сек\n\n"
            
            response += "**🧠 ИИ настройки:**\n"
            response += f"• Статус: `{'Активен' if cerebras_client else 'Отключен'}`\n\n"
            
            response += "**💾 Кэширование:**\n"
            response += f"• Торговые пары: `{CONFIG['cache']['markets_duration']}` сек\n"
            response += f"• Цены: `{CONFIG['cache']['prices_duration']}` сек\n"
            response += f"• Книга ордеров: `{CONFIG['cache']['orderbook_duration']}` сек\n\n"
            
            response += "**📊 Стратегии:**\n"
            for strategy, params in CONFIG['trading']['strategies'].items():
                response += f"• {strategy.upper()}: `{params}`\n"
            
            bot.reply_to(message, response, parse_mode='Markdown')
        
        except Exception as e:
            logging.error(f"Ошибка в show_config: {e}")
            bot.reply_to(message, f"❌ Ошибка получения конфигурации: {e}")

    @bot.message_handler(commands=['donate'])
    def show_donate(message):
        """Показывает информацию о пожертвованиях"""
        donate_text = f"""
💖 **Поддержите разработчика!**
Если этот бот помог вам в торговле, вы можете поддержать разработку:
🔗 **Ссылка для пожертвований:**
{DONATE_URL}
Ваша поддержка поможет:
• 🔧 Улучшить функционал бота
• 🧠 Добавить новые ИИ-возможности  
• 🐛 Быстрее исправлять ошибки
• 📈 Разработать новые стратегии торговли
**Спасибо за вашу поддержку! ❤️**
"""
        
        bot.reply_to(message, donate_text, parse_mode='Markdown')

    # Обработчик всех остальных сообщений
    @bot.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        """Обработчик всех остальных сообщений"""
        bot.reply_to(
            message, 
            "❓ Неизвестная команда. Используйте /help для просмотра доступных команд.",
            reply_markup=menu_markup
        )

# Закрываем блок if bot:
def start_bot():
    """Улучшенный запуск бота с проверками"""
    if not bot:
        logging.error("Telegram бот не инициализирован")
        return
        
    # Проверяем сетевое подключение
    if not check_network_connectivity():
        logging.warning("Проблемы с сетью, настраиваем DNS...")
        configure_dns()
        time.sleep(10)  # Ждем применения настроек
        
        if not check_network_connectivity():
            logging.error("Не удалось восстановить сетевое подключение")
            # Пробуем webhook режим
            if setup_webhook_mode():
                logging.info("Переключились на webhook режим")
                return
            else:
                logging.error("Webhook режим недоступен")
                sys.exit(1)
    
    # Запускаем с retry механизмом
    try:
        bot.infinity_polling_with_retry()
    except Exception as e:
        logging.error(f"Критическая ошибка бота: {e}")
        sys.exit(1)

def run_trading_mode():
    """Режим работы только для торговых операций без Telegram бота"""
    logging.info("🚀 Запуск SafeTrade в режиме торгового бота")
    
    try:
        # Проверяем сетевое подключение
        if not check_network_connectivity():
            logging.warning("Проблемы с сетью, настраиваем DNS...")
            configure_dns()
            time.sleep(10)
            
            if not check_network_connectivity():
                logging.error("Не удалось восстановить сетевое подключение")
                return
        
        logging.info("✅ Сетевое подключение установлено")
        
        # Получаем текущие балансы для проверки
        balances = get_sellable_balances()
        if balances:
            logging.info(f"💰 Найдены балансы: {list(balances.keys())}")
            
            # Запускаем автоматическую продажу
            result = auto_sell_all_altcoins()
            if result["success"]:
                logging.info(f"✅ Автопродажа завершена: {result['message']}")
            else:
                logging.warning(f"⚠️ Автопродажа завершена с ошибками: {result['message']}")
        else:
            logging.info("ℹ️ Нет балансов для продажи")
        
        # Если включен планировщик, работаем в фоне
        if AUTO_SELL_INTERVAL > 0:
            logging.info(f"⏰ Планировщик активен. Следующая автопродажа через {AUTO_SELL_INTERVAL} секунд")
            logging.info("💡 Для остановки нажмите Ctrl+C")
            
            try:
                while True:
                    time.sleep(60)  # Проверяем каждую минуту
            except KeyboardInterrupt:
                logging.info("Получен сигнал остановки")
        else:
            logging.info("✅ Торговая операция завершена")
            
    except Exception as e:
        logging.error(f"❌ Ошибка в торговом режиме: {e}")
    finally:
        logging.info("🏁 Завершение торгового режима")

def main():
    """Главная функция запуска"""
    try:
        logging.info("Запуск SafeTrade Trading Bot...")
        
        # Проверяем обязательные переменные окружения
        if not API_KEY or not API_SECRET:
            logging.error("❌ Отсутствуют обязательные переменные окружения:")
            logging.error("   - SAFETRADE_API_KEY")
            logging.error("   - SAFETRADE_API_SECRET")
            logging.error("Бот не может работать без API ключей SafeTrade")
            return
        
        logging.info("✅ API ключи SafeTrade настроены")
        
        # Проверяем обязательные настройки Supabase
        if not SUPABASE_URL or not SUPABASE_KEY:
            logging.error("❌ Отсутствуют обязательные настройки Supabase:")
            logging.error("   - SAFETRADE_SUPABASE_URL")
            logging.error("   - SAFETRADE_SUPABASE_KEY")
            logging.error("Бот не может работать без Supabase")
            return
        
        logging.info("✅ Supabase настройки проверены")
        
        # Загружаем состояние кэша
        load_cache_state()
        
        # Запускаем планировщик автопродаж (если настроен)
        if AUTO_SELL_INTERVAL > 0:
            start_auto_sell_scheduler()
            logging.info(f"📅 Планировщик автопродаж запущен (интервал: {AUTO_SELL_INTERVAL} сек)")
        
        # Проверяем и запускаем Telegram бота
        if bot and TELEGRAM_BOT_TOKEN:
            logging.info("🤖 Telegram бот настроен")
            
            # Отправляем уведомление о запуске
            if ADMIN_CHAT_ID:
                try:
                    bot.send_message(
                        ADMIN_CHAT_ID,
                        "🚀 **SafeTrade Trading Bot запущен!**\n\nВсе системы готовы к работе.",
                        parse_mode='Markdown'
                    )
                    logging.info("📱 Уведомление о запуске отправлено администратору")
                except Exception as e:
                    logging.error(f"Ошибка отправки уведомления о запуске: {e}")
            
            logging.info("Бот успешно запущен и готов к работе")
            # Запускаем бота
            start_bot()
        else:
            logging.info("📱 Telegram бот не настроен - запускаем в режиме торгового бота")
            # Запускаем в режиме только торговых операций
            run_trading_mode()
        
    except KeyboardInterrupt:
        logging.info("Получен сигнал прерывания")
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
    finally:
        logging.info("Завершение работы бота...")
        # Сохраняем состояние при завершении
        save_cache_state()
        if bot:  # Проверяем, что бот инициализирован
            cancel_all_active_orders()

if __name__ == "__main__":
    main()
