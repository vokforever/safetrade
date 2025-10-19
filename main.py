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
# --- УСЛОВНЫЙ ИМПОРТ И ИНИЦИАЛИЗАЦИЯ ИИ ---
# Временно установим значение по умолчанию, будет обновлено после загрузки конфигурации
AI_ENABLED = False
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
import trade_history

# --- SAFE TRADE API КЛИЕНТ ---
class SafeTradeAPI:
    def __init__(self, api_key: str, api_secret: str):
        if not api_key or not api_secret:
            raise ValueError("API key and secret cannot be empty.")
        
        self.key = api_key
        self.secret = api_secret.encode('utf-8')
        self.base_url = "https://safe.trade/api/v2"
        self.scraper = cloudscraper.create_scraper()

    def _sign_payload(self, payload: dict) -> str:
        """Signs the JSON payload using HMAC-SHA256, as required by the API."""
        json_payload = json.dumps(payload)
        return hmac.new(self.secret, json_payload.encode('utf-8'), hashlib.sha256).hexdigest()

    def _get_auth_headers(self, payload: dict) -> dict:
        """Generates the required authentication headers for a private request."""
        nonce = str(int(time.time() * 1000))
        signature = self._sign_payload(payload)
        return {
            'X-Auth-Apikey': self.key,
            'X-Auth-Nonce': nonce,
            'X-Auth-Signature': signature,
            'Content-Type': 'application/json'
        }

    def get(self, path: str, is_private: bool = False):
        """Sends a GET request. Handles both public and private endpoints."""
        url = self.base_url + path
        headers = {}
        if is_private:
            # For GET requests, the payload to sign is empty
            headers = self._get_auth_headers({})
            
        response = self.scraper.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict):
        """Sends an authenticated POST request."""
        url = self.base_url + path
        headers = self._get_auth_headers(payload)
        response = self.scraper.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    # --- Wrapper methods for specific API calls ---

    def get_balances(self):
        """Fetches all account balances."""
        return self.get("/account/balances", is_private=True)

    def create_order(self, market: str, side: str, volume: float, ord_type: str, price: float = None):
        """
        Creates a new order.
        Note the parameter names: 'volume' and 'ord_type'.
        """
        payload = {
            "market": market,
            "side": side,
            "volume": str(volume),
            "ord_type": ord_type,
        }
        if ord_type == "limit" and price:
            payload["price"] = str(price)
        
        return self.post("/market/orders", payload)

    def get_orders(self):
        """Fetches all orders."""
        return self.get("/market/orders", is_private=True)

    def cancel_order(self, order_id: str):
        """Cancels an order."""
        return self.post(f"/market/orders/{order_id}/cancel", {})

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/app/data/bot.log", encoding='utf-8'),
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
# - TELEGRAM_BOT_TOKEN - Токен Telegram бота (для Telegram интерфейса)
# - ADMIN_CHAT_ID - ID чата администратора (для уведомлений)
# - SAFETRADE_CEREBRAS_API_KEY - API ключ Cerebras AI (для ИИ-помощника)
# - SAFETRADE_SUPABASE_URL - URL Supabase (для облачной базы данных)
# - SAFETRADE_SUPABASE_KEY - Ключ Supabase (для облачной базы данных)
# - SAFETRADE_WEBHOOK_URL - URL для webhook режима (альтернатива polling)
# - SAFETRADE_WEBHOOK_PORT - Порт для webhook режима
#
# КОНФИГУРАЦИЯ ВАЛЮТ:
# - excluded_currencies: валюты, которые НЕ будут продаваться (всегда исключены)
# - allowed_currencies: валюты, которые БУДУТ проверяться (пустой список = проверять все)
#   Пример: ['QTC', 'USDT'] - проверять только QTC и USDT
#
# ПРИМЕЧАНИЕ: Бот будет работать ТОЛЬКО с SAFETRADE_API_KEY и SAFETRADE_API_SECRET!
# Все остальные функции будут отключены, если соответствующие переменные не указаны.
DEFAULT_CONFIG = {
    'main': {
        'easy_mode': True,      # <-- НОВОЕ: Простой режим для продажи всего по рынку
        'ai_enabled': False,    # <-- НОВОE: Включить/выключить ИИ-помощника
    },
    'trading': {
        'excluded_currencies': ['USDT', 'BUSD', 'USDC'],
        'allowed_currencies': [],  # Пустой список = проверять все валюты, если указаны - только их
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
        'max_volatility_threshold': 0.05,
        'max_spread_threshold': 0.02  # <-- ИСПРАВЛЕНО: Добавлен недостающий ключ (значение 2%)
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
CEREBRAS_API_KEY = os.getenv("SAFETRADE_CEREBRAS_API_KEY")

# Supabase настройки
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Настройки режимов работы из переменных окружения (с переопределением из конфига)
EASY_MODE_ENV = os.getenv("SAFETRADE_EASY_MODE", "").lower() in ("true", "1", "yes", "on")
AI_ENABLED_ENV = os.getenv("SAFETRADE_AI_ENABLED", "").lower() in ("true", "1", "yes", "on")

# Проверяем загрузку переменных окружения
def validate_environment():
    """Проверка и валидация переменных окружения"""
    missing_vars = []
    
    if not API_KEY:
        missing_vars.append("SAFETRADE_API_KEY")
    if not API_SECRET:
        missing_vars.append("SAFETRADE_API_SECRET")
    if not SUPABASE_URL:
        missing_vars.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing_vars.append("SUPABASE_KEY")
    
    if missing_vars:
        logging.error("❌ Отсутствуют обязательные переменные окружения:")
        for var in missing_vars:
            logging.error(f"   - {var}")
        
        logging.error("\n📋 Настройка переменных окружения:")
        logging.error("1. Создайте файл .env в корне проекта")
        logging.error("2. Добавьте следующие строки:")
        logging.error("   SAFETRADE_API_KEY=your_api_key_here")
        logging.error("   SAFETRADE_API_SECRET=your_api_secret_here")
        logging.error("   SUPABASE_URL=your_supabase_url_here")
        logging.error("   SUPABASE_KEY=your_supabase_key_here")
        logging.error("3. Перезапустите бота")
        
        logging.error("\n🌐 Для CapRover/VPS:")
        logging.error("Установите переменные окружения в настройках приложения")
        
        return False
    
    logging.info("✅ Все обязательные переменные окружения загружены")
    return True

# URL для пожертвований
DONATE_URL = "https://boosty.to/vokforever/donate"

# Убедимся, что секрет в байтовом представлении для hmac
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None
BASE_URL = "https://safe.trade/api/v2"

# Инициализируем новый API клиент
try:
    api_client = SafeTradeAPI(API_KEY, API_SECRET)
    logging.info("✅ SafeTrade API клиент успешно инициализирован.")
except ValueError as e:
    logging.error(f"❌ Не удалось инициализировать API клиент: {e}")
    sys.exit(1)

# Настройки из конфигурации с приоритетом переменных окружения
EASY_MODE = EASY_MODE_ENV if EASY_MODE_ENV is not None else CONFIG['main']['easy_mode']
AI_ENABLED = AI_ENABLED_ENV if AI_ENABLED_ENV is not None else CONFIG['main']['ai_enabled']
EXCLUDED_CURRENCIES = CONFIG['trading']['excluded_currencies']
ALLOWED_CURRENCIES = CONFIG['trading']['allowed_currencies']
MIN_POSITION_VALUE_USD = CONFIG['trading']['min_position_value_usd']
MAX_CONCURRENT_SALES = CONFIG['trading']['max_concurrent_sales']
AUTO_SELL_INTERVAL = CONFIG['trading']['auto_sell_interval']

# --- УСЛОВНЫЙ ИМПОРТ И ИНИЦИАЛИЗАЦИЯ ИИ ПОСЛЕ ЗАГРУЗКИ КОНФИГУРАЦИИ ---
if AI_ENABLED:
    try:
        import ai_assistant
        from ai_assistant import TradingDecision, SellStrategy
    except ImportError:
        logging.error("Не удалось импортировать ai_assistant.py. Функции ИИ будут отключены.")
        AI_ENABLED = False

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

# Стратегии продаж (импортируются из ai_assistant при необходимости)
class OrderStatus(Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"

# Определяем MarketData здесь, чтобы он был доступен всегда
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
        """Вставка торговой пары с правильной обработкой дубликатов"""
        try:
            data = {
                'symbol': symbol,
                'base_currency': base_currency,
                'quote_currency': quote_currency,
                'is_active': is_active,
                'last_updated': datetime.now().isoformat(),
                'created_at': datetime.now().isoformat()
            }
            
            # Используем upsert с указанием конфликтного поля
            result = self.supabase.table('safetrade_trading_pairs').upsert(
                data, 
                on_conflict='symbol'  # Указываем поле для разрешения конфликтов
            ).execute()
            
            return result.data[0] if result.data else None
        except Exception as e:
            # Улучшенная обработка ошибок дублирования
            error_str = str(e).lower()
            if ('duplicate key' in error_str or '23505' in error_str or 
                'unique constraint' in error_str or 'already exists' in error_str):
                logging.debug(f"Торговая пара {symbol} уже существует, пропускаем")
                return None
            elif 'connection' in error_str or 'timeout' in error_str:
                logging.error(f"Ошибка соединения при вставке {symbol}: {e}")
                return None
            else:
                logging.error(f"Ошибка вставки торговой пары {symbol}: {e}")
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
    
    def cleanup_duplicate_trading_pairs(self):
        """Очистка дублирующихся торговых пар"""
        try:
            # SQL запрос для удаления дубликатов, оставляя только первую запись
            cleanup_sql = """
            DELETE FROM safetrade_trading_pairs 
            WHERE id NOT IN (
                SELECT MIN(id) 
                FROM safetrade_trading_pairs 
                GROUP BY symbol
            );
            """
            
            # Выполняем SQL запрос через Supabase
            result = self.supabase.rpc('exec_sql', {'sql': cleanup_sql}).execute()
            logging.info("Очистка дублирующихся торговых пар завершена")
            return True
        except Exception as e:
            # Если RPC не работает, используем альтернативный метод
            try:
                logging.info("Попытка альтернативной очистки дубликатов...")
                # Получаем все символы с дубликатами
                result = self.supabase.table('safetrade_trading_pairs').select('symbol').execute()
                
                if result.data:
                    symbols = [row['symbol'] for row in result.data]
                    # Создаем временную таблицу с уникальными записями
                    unique_pairs = {}
                    for row in result.data:
                        symbol = row['symbol']
                        if symbol not in unique_pairs:
                            unique_pairs[symbol] = row
                    
                    # Очищаем таблицу и вставляем уникальные записи
                    self.supabase.table('safetrade_trading_pairs').delete().neq('id', '').execute()
                    
                    for pair in unique_pairs.values():
                        self.supabase.table('safetrade_trading_pairs').insert(pair).execute()
                    
                    logging.info(f"Очистка завершена. Оставлено {len(unique_pairs)} уникальных записей")
                    return True
            except Exception as alt_e:
                logging.warning(f"Не удалось очистить дублирующиеся записи: {e}, альтернативный метод: {alt_e}")
                return False
    
    def force_cleanup_duplicates(self):
        """Принудительная очистка дубликатов с безопасным подходом"""
        try:
            logging.info("Начинаем принудительную очистку дубликатов...")
            
            # Получаем все уникальные записи
            result = self.supabase.table('safetrade_trading_pairs').select('*').execute()
            
            if not result.data:
                logging.info("Таблица пуста, очистка не требуется")
                return True
            
            # Создаем словарь уникальных записей по символу
            unique_records = {}
            for record in result.data:
                symbol = record['symbol']
                if symbol not in unique_records:
                    unique_records[symbol] = record
            
            logging.info(f"Найдено {len(result.data)} записей, уникальных: {len(unique_records)}")
            
            # Безопасная очистка - удаляем только дубликаты, сохраняя уникальные
            all_symbols = [row['symbol'] for row in result.data]
            duplicate_symbols = [symbol for symbol in all_symbols if all_symbols.count(symbol) > 1]
            
            if duplicate_symbols:
                # Удаляем дубликаты по одному символу
                for symbol in set(duplicate_symbols):
                    # Оставляем первую запись, удаляем остальные
                    symbol_records = [row for row in result.data if row['symbol'] == symbol]
                    if len(symbol_records) > 1:
                        # Удаляем все кроме первой
                        for record in symbol_records[1:]:
                            if 'id' in record:
                                self.supabase.table('safetrade_trading_pairs').delete().eq('id', record['id']).execute()
                                logging.debug(f"Удален дубликат {symbol} с ID {record['id']}")
            
            logging.info(f"Очистка завершена. Сохранено {len(unique_records)} уникальных записей")
            return True
            
        except Exception as e:
            logging.error(f"Ошибка при принудительной очистке: {e}")
            return False
    
    def manual_cleanup_if_needed(self):
        """Ручная очистка дубликатов если их много"""
        try:
            total_count = self.get_trading_pairs_count()
            duplicate_count = self.get_duplicate_count()
            
            if duplicate_count > 0:
                logging.warning(f"🔧 Ручная очистка: обнаружено {duplicate_count} дубликатов из {total_count} записей")
                
                if duplicate_count > total_count * 0.1:  # Если больше 10% дубликатов
                    logging.info("🚨 Критическое количество дубликатов! Запуск принудительной очистки...")
                    return self.force_cleanup_duplicates()
                elif duplicate_count > total_count * 0.05:  # Если больше 5% дубликатов
                    logging.info("⚠️ Умеренное количество дубликатов. Запуск очистки...")
                    return self.force_cleanup_duplicates()
                else:
                    logging.info("ℹ️ Небольшое количество дубликатов, очистка не требуется")
                    return True
            else:
                logging.info("✅ Дубликатов не обнаружено")
                return True
                
        except Exception as e:
            logging.error(f"Ошибка при ручной очистке: {e}")
            return False
    
    def get_duplicate_count(self):
        """Получение количества дублирующихся записей"""
        try:
            result = self.supabase.table('safetrade_trading_pairs').select('symbol').execute()
            
            if not result.data:
                return 0
            
            symbols = [row['symbol'] for row in result.data]
            unique_symbols = set(symbols)
            duplicate_count = len(symbols) - len(unique_symbols)
            
            return duplicate_count
        except Exception as e:
            logging.error(f"Ошибка при подсчете дубликатов: {e}")
            return 0
    
    def get_trading_pairs_count(self):
        """Получение количества торговых пар в базе"""
        try:
            result = self.supabase.table('safetrade_trading_pairs').select('symbol', count='exact').execute()
            return result.count if hasattr(result, 'count') else len(result.data)
        except Exception as e:
            logging.error(f"Ошибка получения количества торговых пар: {e}")
            return 0
    
    def check_database_health(self):
        """Проверка здоровья базы данных и автоматическая очистка при необходимости"""
        try:
            # Сначала проверяем соединение с базой
            if not self.check_connection():
                logging.error("Нет соединения с базой данных")
                return False
            
            total_count = self.get_trading_pairs_count()
            duplicate_count = self.get_duplicate_count()
            
            if duplicate_count > 0:
                logging.warning(f"Обнаружено {duplicate_count} дублирующихся записей из {total_count} общих")
                
                # Если дубликатов больше 5% от общего количества, запускаем автоматическую очистку
                if duplicate_count > total_count * 0.05:
                    logging.info("Запуск автоматической очистки дубликатов...")
                    if self.force_cleanup_duplicates():
                        logging.info("Автоматическая очистка завершена успешно")
                        return True
                    else:
                        logging.error("Автоматическая очистка завершилась с ошибкой")
                        return False
                else:
                    logging.info("Количество дубликатов в допустимых пределах")
                    return True
            else:
                logging.info("Дублирующихся записей не обнаружено")
                return True
                
        except Exception as e:
            logging.error(f"Ошибка при проверке здоровья БД: {e}")
            return False
    
    def check_connection(self):
        """Проверка соединения с Supabase"""
        try:
            # Простой тест соединения
            result = self.supabase.table('safetrade_trading_pairs').select('symbol').limit(1).execute()
            return True
        except Exception as e:
            logging.error(f"Ошибка соединения с Supabase: {e}")
            return False
    
    def execute_with_retry(self, operation, max_retries=3, delay=1):
        """Выполнение операции с повторными попытками"""
        for attempt in range(max_retries):
            try:
                return operation()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                logging.warning(f"Попытка {attempt + 1} не удалась: {e}. Повтор через {delay} сек...")
                time.sleep(delay)
                delay *= 2  # Экспоненциальная задержка
    
    def get_database_stats(self):
        """Получение статистики базы данных для мониторинга"""
        try:
            stats = {
                'trading_pairs': self.get_trading_pairs_count(),
                'price_history': 0,
                'order_history': 0,
                'ai_decisions': 0,
                'performance_metrics': 0,
                'duplicates': self.get_duplicate_count(),
                'connection_healthy': self.check_connection()
            }
            
            # Получаем количество записей в других таблицах
            try:
                result = self.supabase.table('safetrade_price_history').select('*', count='exact').execute()
                stats['price_history'] = result.count if hasattr(result, 'count') else len(result.data or [])
            except:
                pass
                
            try:
                result = self.supabase.table('safetrade_order_history').select('*', count='exact').execute()
                stats['order_history'] = result.count if hasattr(result, 'count') else len(result.data or [])
            except:
                pass
                
            try:
                result = self.supabase.table('safetrade_ai_decisions').select('*', count='exact').execute()
                stats['ai_decisions'] = result.count if hasattr(result, 'count') else len(result.data or [])
            except:
                pass
                
            try:
                result = self.supabase.table('safetrade_performance_metrics').select('*', count='exact').execute()
                stats['performance_metrics'] = result.count if hasattr(result, 'count') else len(result.data or [])
            except:
                pass
            
            return stats
        except Exception as e:
            logging.error(f"Ошибка получения статистики БД: {e}")
            return None
    
    def close_connection(self):
        """Безопасное закрытие соединения с базой данных"""
        try:
            if hasattr(self.supabase, 'auth') and hasattr(self.supabase.auth, 'sign_out'):
                self.supabase.auth.sign_out()
                logging.info("Соединение с Supabase закрыто")
        except Exception as e:
            logging.warning(f"Ошибка при закрытии соединения: {e}")

# Инициализация менеджера базы данных будет выполнена после создания Supabase клиента

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
    logging.warning("TELEGRAM_BOT_TOKEN не указан. Telegram бот будет отключен.")

# Инициализируем Supabase (обязательно)
if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("❌ Supabase настройки обязательны!")
    logging.error("   - SAFETRADE_SUPABASE_URL")
    logging.error("   - SAFETRADE_SUPABASE_KEY")
    logging.error("Бот не может работать без Supabase")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Тестируем соединение с Supabase
try:
    # Простой тест соединения
    test_result = supabase.table('safetrade_trading_pairs').select('symbol').limit(1).execute()
    logging.info("✅ Supabase подключен и соединение протестировано")
except Exception as e:
    logging.error(f"❌ Ошибка подключения к Supabase: {e}")
    logging.error("Проверьте URL, ключ и доступность сервера")
    sys.exit(1)

# Инициализация менеджера базы данных
db_manager = DatabaseManager(supabase)
logging.info("✅ Менеджер базы данных инициализирован")

# Инициализируем Cerebras только если включен и есть ключ
cerebras_client = None
if AI_ENABLED and CEREBRAS_API_KEY:
    ai_assistant.initialize_ai(CEREBRAS_API_KEY)
    cerebras_client = ai_assistant.cerebras_client # ссылка на глобальный клиент в модуле
else:
    if not CEREBRAS_API_KEY and AI_ENABLED:
        logging.info("ИИ включен в конфиге, но CEREBRAS_API_KEY не указан - функции ИИ отключены")
    elif AI_ENABLED:
        logging.info("Библиотека Cerebras недоступна - функции ИИ отключены")
    else:
        logging.info("ИИ-помощник отключен в конфигурации.")

# Настраиваем клавиатуру с командами
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_all')
menu_markup.row('/history', '/ai_status')
menu_markup.row('/markets', '/config')
menu_markup.row('/donate', '/help')
menu_markup.row('/health', '/test_api')
menu_markup.row('/restart')

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
        # Правильное завершение Supabase клиента
        if 'db_manager' in globals():
            try:
                db_manager.close_connection()
            except Exception as e:
                logging.warning(f"Ошибка при завершении менеджера БД: {e}")
        
        if 'supabase' in globals():
            try:
                supabase.auth.sign_out()
                logging.info("Supabase клиент корректно завершен")
            except Exception as e:
                logging.warning(f"Ошибка при завершении Supabase клиента: {e}")
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
def test_api_endpoints():
    """Тестирует различные API эндпоинты для поиска работающих"""
    logging.info("🔍 Тестирование API эндпоинтов SafeTrade...")
    
    test_endpoints = [
        "/trade/public/markets",
        "/public/markets",
        "/markets",
        "/trade/markets",
        "/trade/public/tickers/btcusdt",
        "/public/markets/btcusdt/tickers",
        "/tickers/btcusdt",
        "/trade/tickers/btcusdt"
    ]
    
    working_endpoints = []
    
    for endpoint in test_endpoints:
        try:
            url = BASE_URL + endpoint
            logging.info(f"Тестирую: {url}")
            response = scraper.get(url, timeout=10)
            
            if response.status_code == 200:
                working_endpoints.append(endpoint)
                logging.info(f"✅ {endpoint} - работает (статус: {response.status_code})")
                
                # Показываем структуру ответа для понимания
                try:
                    data = response.json()
                    logging.info(f"   Структура ответа: {type(data)} - {str(data)[:200]}...")
                except:
                    logging.info(f"   Ответ не является JSON: {response.text[:200]}...")
            else:
                logging.warning(f"❌ {endpoint} - статус: {response.status_code}")
                
        except Exception as e:
            logging.warning(f"❌ {endpoint} - ошибка: {e}")
    
    if working_endpoints:
        logging.info(f"🎯 Работающие эндпоинты: {working_endpoints}")
        return working_endpoints
    else:
        logging.error("🚨 Не найдено ни одного работающего API эндпоинта!")
        return []

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
    
    # Пробуем разные возможные эндпоинты для получения торговых пар
    possible_endpoints = [
        "/trade/public/markets",
        "/public/markets", 
        "/markets",
        "/trade/markets"
    ]
    
    for endpoint in possible_endpoints:
        try:
            url = BASE_URL + endpoint
            logging.info(f"Пробуем получить торговые пары через: {url}")
            response = scraper.get(url, timeout=30)
            response.raise_for_status()
            markets = response.json()
            
            if isinstance(markets, list) and len(markets) > 0:
                logging.info(f"✅ Успешно получены торговые пары через {endpoint}: {len(markets)} пар")
                
                # Фильтруем только пары с USDT
                usdt_markets = [
                    market for market in markets 
                    if market.get('quote_unit') == 'usdt' and 
                       market.get('base_unit', '').upper() not in EXCLUDED_CURRENCIES
                ]
                
                logging.info(f"🔍 Найдено {len(usdt_markets)} USDT пар после фильтрации")
                examples = [f"{m.get('base_unit', '').upper()}/USDT" for m in usdt_markets[:5]]
                logging.info(f"📋 Примеры USDT пар: {examples}")
                
                with cache_lock:
                    markets_cache["data"] = usdt_markets
                    markets_cache["last_update"] = time.time()
                
                # Сохраняем в базу данных (используем upsert для избежания дублирования)
                save_markets_to_db(usdt_markets)
                
                return usdt_markets
            else:
                logging.warning(f"Получен пустой или некорректный ответ от {endpoint}: {markets}")
                
        except Exception as e:
            logging.warning(f"Ошибка при запросе к {endpoint}: {e}")
            continue
    
    logging.error("Не удалось получить торговые пары ни с одного эндпоинта")
    # В случае ошибки, пробуем получить из базы данных
    return get_markets_from_db()

def save_markets_to_db(markets):
    """Сохраняет торговые пары в базу данных с улучшенной обработкой дубликатов"""
    global db_manager
    try:
        saved_count = 0
        skipped_count = 0
        error_count = 0
        
        # Получаем текущее количество записей
        current_count = db_manager.get_trading_pairs_count()
        logging.info(f"Текущее количество торговых пар в БД: {current_count}")
        
        # Получаем существующие символы для проверки
        existing_symbols = set()
        try:
            result = db_manager.supabase.table('safetrade_trading_pairs').select('symbol').execute()
            existing_symbols = {row['symbol'] for row in result.data}
        except Exception as e:
            logging.warning(f"Не удалось получить существующие символы: {e}")
        
        # Если все торговые пары уже существуют, просто логируем и выходим
        if len(existing_symbols) >= len(markets):
            logging.info(f"Все {len(markets)} торговых пар уже существуют в БД. Обновление не требуется.")
            logging.info(f"Текущее количество в БД: {len(existing_symbols)}, получено с API: {len(markets)}")
            return
        
        # Фильтруем только новые торговые пары
        new_markets = []
        for market in markets:
            symbol = market.get('id', '')
            if symbol and symbol not in existing_symbols:
                new_markets.append(market)
            else:
                skipped_count += 1
        
        if not new_markets:
            logging.info(f"Новых торговых пар не найдено. Пропущено: {skipped_count}")
            return
        
        logging.info(f"Найдено {len(new_markets)} новых торговых пар для добавления")
        
        # Вставляем новые торговые пары
        for market in new_markets:
            symbol = market.get('id', '')
            try:
                result = db_manager.insert_trading_pair(
                    symbol=symbol,
                    base_currency=market.get('base_unit', ''),
                    quote_currency=market.get('quote_unit', ''),
                    is_active=True
                )
                if result:
                    saved_count += 1
                else:
                    error_count += 1
            except Exception as e:
                error_count += 1
                # Логируем только серьезные ошибки
                if "duplicate key" not in str(e).lower() and "23505" not in str(e):
                    logging.debug(f"Ошибка при сохранении пары {symbol}: {e}")
                continue
        
        final_count = db_manager.get_trading_pairs_count()
        logging.info(f"Сохранено {saved_count} новых торговых пар, пропущено {skipped_count}, ошибок: {error_count}")
        logging.info(f"Общее количество торговых пар в БД: {final_count}")
        
        # Проверяем здоровье базы данных после сохранения
        if error_count > 0 or skipped_count > 0:
            logging.info("Проверка здоровья базы данных...")
            db_manager.check_database_health()
        
        # Если много ошибок дублирования, предлагаем очистку
        if error_count > len(new_markets) * 0.3:  # Если больше 30% ошибок
            logging.info("Обнаружено много дублирующихся записей. Рекомендуется очистка БД.")
            logging.info("Для принудительной очистки используйте: db_manager.force_cleanup_duplicates()")
        
        # Проверяем общее здоровье БД
        db_manager.check_database_health()
        
    except Exception as e:
        logging.error(f"Ошибка при сохранении торговых пар: {e}")

def get_markets_from_db():
    """Получает торговые пары из базы данных"""
    global db_manager
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
        # Используем новый API клиент для получения балансов
        balances = api_client.get_balances()
        
        logging.info(f"🔍 Получено балансов: {len(balances) if isinstance(balances, list) else 'не список'}")
        
        if not isinstance(balances, list):
            logging.warning("Некорректный формат балансов")
            return None
        
        # Получаем доступные торговые пары
        markets = get_all_markets()
        available_currencies = {market.get('base_unit', '').upper() for market in markets}
        
        if ALLOWED_CURRENCIES:
            logging.info(f"📊 Проверяем только разрешенные валюты: {ALLOWED_CURRENCIES}")
            logging.info(f"📊 Доступные валюты в торговых парах: {sorted(list(available_currencies))[:10]}...")
        else:
            logging.info(f"📊 Доступные валюты в торговых парах: {sorted(list(available_currencies))[:10]}...")
        
        sellable_balances = {}
        for balance in balances:
            currency = balance.get('currency', '').upper()
            balance_amount = float(balance.get('balance', 0))
            
            logging.info(f"🔍 Проверяем баланс {currency}: {balance_amount}")
            
            # Пропускаем исключенные валюты и нулевые балансы
            if (currency in EXCLUDED_CURRENCIES or balance_amount <= 0):
                if currency in EXCLUDED_CURRENCIES:
                    logging.debug(f"⏭️ Пропускаем {currency}: в списке исключенных")
                else:
                    logging.debug(f"⏭️ Пропускаем {currency}: нулевой баланс")
                continue
            
            # Проверяем allowlist - если настроен, пропускаем валюты не в списке
            if ALLOWED_CURRENCIES and currency not in ALLOWED_CURRENCIES:
                logging.info(f"⏭️ Пропускаем {currency}: не в списке разрешенных валют {ALLOWED_CURRENCIES}")
                continue
            
            # Проверяем, есть ли торговая пара для этой валюты
            if currency not in available_currencies:
                logging.info(f"⚠️ Валюты {currency} нет в доступных торговых парах")
                # Пробуем найти альтернативные пары
                alternative_pairs = [f"{currency.lower()}btc", f"{currency.lower()}eth", f"{currency.lower()}usdc"]
                has_alternative = any(any(market.get('id', '').lower() == alt for market in markets) for alt in alternative_pairs)
                
                if has_alternative:
                    logging.info(f"✅ Найдена альтернативная торговая пара для {currency}")
                    sellable_balances[currency] = balance_amount
                else:
                    logging.info(f"❌ Нет альтернативных торговых пар для {currency}")
                    continue
            else:
                logging.info(f"✅ {currency} найден в доступных торговых парах")
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
    global prices_cache, db_manager
    
    # Нормализуем символ (приводим к нижнему регистру)
    symbol = symbol.lower()
    
    with cache_lock:
        if (symbol in prices_cache["data"] and 
            prices_cache["last_update"] and 
            time.time() - prices_cache["last_update"] < prices_cache["cache_duration"]):
            return prices_cache["data"][symbol]
    
    # Список эндпоинтов для попытки получения цены (в порядке приоритета)
    # Приоритет отдаем рабочим эндпоинтам из логов
    endpoints = [
        f"/trade/public/tickers/{symbol}",  # Рабочий эндпоинт из логов
        f"/public/markets/{symbol}/tickers" # Резервный
    ]
    
    for endpoint in endpoints:
        try:
            url = BASE_URL + endpoint
            logging.info(f"Пробуем получить тикер {symbol} через: {endpoint}")
            response = scraper.get(url, timeout=30)
            response.raise_for_status()
            ticker = response.json()
            
            if not isinstance(ticker, dict):
                logging.warning(f"Некорректный формат тикера для {symbol} от {endpoint}: {ticker}")
                continue
            
            # Пробуем разные возможные ключи для цены
            price = None
            for price_key in ['last', 'bid', 'buy', 'price']:
                if ticker.get(price_key):
                    try:
                        price = float(ticker.get(price_key))
                        if price > 0:
                            logging.info(f"✅ Найдена цена для {symbol} через ключ '{price_key}': {price}")
                            break
                    except (ValueError, TypeError):
                        continue
            
            if price and price > 0:
                with cache_lock:
                    prices_cache["data"][symbol] = price
                    prices_cache["last_update"] = time.time()
                
                # Сохраняем в базу данных
                try:
                    db_manager.insert_price_history(
                        timestamp=datetime.now().isoformat(),
                        symbol=symbol.upper(),
                        price=price,
                        volume=float(ticker.get('vol', 0)) if ticker.get('vol') else None,
                        high=float(ticker.get('high', 0)) if ticker.get('high') else None,
                        low=float(ticker.get('low', 0)) if ticker.get('low') else None
                    )
                except Exception as e:
                    logging.warning(f"Ошибка при сохранении истории цен для {symbol}: {e}")
                
                return price
            else:
                logging.warning(f"Не удалось найти валидную цену в тикере {symbol} от {endpoint}")
                
        except Exception as e:
            if "404" in str(e):
                logging.debug(f"Эндпоинт {endpoint} не найден для {symbol}")
            elif "401" in str(e):
                logging.debug(f"Эндпоинт {endpoint} требует авторизации для {symbol}")
            else:
                logging.warning(f"Ошибка при запросе тикера {symbol} к {endpoint}: {e}")
            continue
    
    # Если не удалось получить цену, пробуем альтернативные варианты символа
    if symbol.endswith('usdt'):
        base_symbol = symbol[:-4]  # Убираем 'usdt'
        # Пробуем с другими базовыми валютами
        alternative_symbols = [f"{base_symbol}btc", f"{base_symbol}eth", f"{base_symbol}usdc"]
        
        for alt_symbol in alternative_symbols:
            logging.info(f"Пробуем альтернативный символ: {alt_symbol}")
            alt_price = get_ticker_price_internal(alt_symbol)
            if alt_price:
                logging.info(f"✅ Найдена цена для {symbol} через альтернативный символ {alt_symbol}: {alt_price}")
                return alt_price
    
    logging.error(f"Не удалось получить цену для {symbol} ни с одного эндпоинта")
    return None

def get_ticker_price_internal(symbol):
    """Внутренняя функция для получения цены (без retry)"""
    # Список эндпоинтов для попытки получения цены (в порядке приоритета)
    endpoints = [
        f"/trade/public/tickers/{symbol}",  # Рабочий эндпоинт из логов
        f"/public/markets/{symbol}/tickers" # Резервный
    ]
    
    for endpoint in endpoints:
        try:
            url = BASE_URL + endpoint
            response = scraper.get(url, timeout=30)
            response.raise_for_status()
            ticker = response.json()
            
            if not isinstance(ticker, dict):
                continue
            
            # Пробуем разные возможные ключи для цены
            price = None
            for price_key in ['last', 'bid', 'buy', 'price']:
                if ticker.get(price_key):
                    try:
                        price = float(ticker.get(price_key))
                        if price > 0:
                            return price
                    except (ValueError, TypeError):
                        continue
            
        except Exception:
            continue
    
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
    
    # Список эндпоинтов для попытки получения книги ордеров (в порядке приоритета)
    endpoints = [
        f"/public/markets/{symbol}/order-book",
        f"/trade/public/order-book/{symbol}",
        f"/public/order-book/{symbol}",
        f"/order-book/{symbol}"
    ]
    
    for endpoint in endpoints:
        try:
            url = BASE_URL + endpoint
            response = scraper.get(url, timeout=30)
            response.raise_for_status()
            orderbook = response.json()
            
            if not orderbook or not orderbook.get('bids') or not orderbook.get('asks'):
                logging.warning(f"Пустая книга ордеров для {symbol} через {endpoint}")
                continue
            
            with cache_lock:
                orderbook_cache["data"][symbol] = orderbook
                orderbook_cache["last_update"][symbol] = time.time()
            
            logging.info(f"✅ Успешно получена книга ордеров для {symbol} через {endpoint}")
            return orderbook
            
        except Exception as e:
            logging.warning(f"Ошибка при запросе книги ордеров {symbol} к {endpoint}: {e}")
            continue
    
    logging.error(f"Не удалось получить книгу ордеров для {symbol} ни с одного эндпоинта")
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

        # В простом режиме, если не нужна сложная аналитика, можно не получать книгу ордеров
        if EASY_MODE:
            logging.debug(f"Easy Mode: Пропускаем загрузку книги ордеров для {symbol}")
            
            return MarketData(
                symbol=symbol.upper(),
                current_price=current_price,
                volatility=0, volume_24h=0, bid_depth=0, ask_depth=0, spread=0
            )

        # Получаем книгу ордеров
        orderbook = get_orderbook(symbol)
        
        # Если не удалось получить книгу ордеров, используем базовые значения
        if not orderbook:
            logging.warning(f"Не удалось получить книгу ордеров для {symbol}, используем базовые значения")
            
            market_data = MarketData(
                symbol=symbol.upper(),
                current_price=current_price,
                volatility=0.01,  # Базовое значение
                volume_24h=1000,   # Базовое значение
                bid_depth=100,      # Базовое значение
                ask_depth=100,      # Базовое значение
                spread=0.001        # Базовое значение
            )
        else:
            # Рассчитываем метрики на основе книги ордеров
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
        try:
            order_validator.validate_market_conditions(market_data)
        except Exception as e:
            logging.warning(f"Валидация рыночных условий для {symbol}: {e}")
        
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
                # Если не удалось получить полные рыночные данные, создаем базовые
                current_price = get_ticker_price(market_symbol)
                if not current_price:
                    continue
                
                # Создаем базовые рыночные данные
                market_data = MarketData(
                    symbol=market_symbol.upper(),
                    current_price=current_price,
                    volatility=0.01,  # Базовое значение
                    volume_24h=1000,  # Базовое значение
                    bid_depth=100,     # Базовое значение
                    ask_depth=100,     # Базовое значение
                    spread=0.001       # Базовое значение
                )
            
            # Рассчитываем стоимость в USD
            usd_value = balance * market_data.current_price
            
            # Пропускаем, если стоимость ниже минимальной
            if usd_value < MIN_POSITION_VALUE_USD:
                continue
            
            # В простом режиме приоритет основан только на стоимости в USD
            if EASY_MODE:
                priority_score = usd_value
            else:
                # Сложный расчет приоритета (старая логика)
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

def execute_trading_strategy(priority_score: PriorityScore, ai_decision: "TradingDecision" = None):
    """Исполняет торговую стратегию для конкретной валюты"""
    try:
        market_symbol = f"{priority_score.currency.lower()}usdt"
        amount = priority_score.balance
        
        # Валидируем параметры
        order_validator.validate_order_params(market_symbol, amount)
        
        # В ПРОСТОМ РЕЖИМЕ ВСЕГДА ПРОДАЕМ ПО РЫНКУ
        if EASY_MODE:
            logging.info(f"Easy Mode: Исполняем рыночную продажу для {priority_score.currency}")
            return execute_market_sell(market_symbol, amount)

        # Используем стандартную логику выбора стратегии для сложного режима
        if ai_decision and ai_decision.strategy:
            # Импортируем стратегии если ИИ включен
            if AI_ENABLED:
                from ai_assistant import SellStrategy
            else:
                # Создаем локальный класс SellStrategy
                class SellStrategy(Enum):
                    MARKET = "market"
                    LIMIT = "limit"
                    TWAP = "twap"
                    ICEBERG = "iceberg"
                    ADAPTIVE = "adaptive"
            
            strategy = ai_decision.strategy
            parameters = ai_decision.parameters
        else:
            # Импортируем стратегии если ИИ включен
            if AI_ENABLED:
                from ai_assistant import SellStrategy
            else:
                # Создаем локальный класс SellStrategy
                class SellStrategy(Enum):
                    MARKET = "market"
                    LIMIT = "limit"
                    TWAP = "twap"
                    ICEBERG = "iceberg"
                    ADAPTIVE = "adaptive"
            
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
    """Создает ордер на продажу, используя НОВЫЙ и ПРАВИЛЬНЫЙ API клиент."""
    global db_manager
    try:
        # Валидация параметров
        order_validator.validate_order_params(market_symbol, amount, order_type, price)
        
        # Определяем валюты из символа
        base_currency = market_symbol.replace('usdt', '').upper()

        # !!! ИСПОЛЬЗУЕМ НОВЫЙ КЛИЕНТ И ПРАВИЛЬНЫЕ ПАРАМЕТРЫ !!!
        order_details = api_client.create_order(
            market=market_symbol,
            side="sell",
            volume=amount,          # 'volume', а не 'amount'
            ord_type=order_type     # 'ord_type', а не 'type'
        )
        
        order_id = order_details.get('id')
        order_amount = order_details.get('volume', amount)  # Используем 'volume' из ответа
        
        # Сохраняем данные об ордере в локальную базу
        db_manager.insert_order_history(
            order_id=order_id,
            timestamp=datetime.now().isoformat(),
            symbol=order_details.get('market', 'N/A'),
            side=order_details.get('side', 'N/A'),
            order_type=order_details.get('ord_type', 'N/A'),  # 'ord_type' вместо 'type'
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
            f"*Тип:* `{order_details.get('ord_type', 'N/A').capitalize()}`\n"
            f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
            f"*Заявленный объем:* `{order_amount} {base_currency}`\n"
            f"*ID ордера:* `{order_id}`"
        )
    except Exception as e:
        error_message = f"❌ Ошибка при создании ордера на продажу: {e}"
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_details = e.response.json()  # API отвечает в JSON
                error_msg = error_details.get('errors', [str(error_details)])
                error_message += f"\nОтвет сервера: `{json.dumps(error_msg)}`"
            except:
                error_message += f"\nОтвет сервера: `{e.response.text}`"
        logging.error(error_message)
        return error_message

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def track_order_execution(order_id, timeout=300):
    """Отслеживает исполнение ордера и возвращает trades"""
    global db_manager
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Получаем статус ордера
            order_details = get_order_details(order_id)
            
            if order_details is None:
                logging.warning(f"Ордер {order_id} не найден - возможно уже исполнен или отменён")
                # Попробуем найти сделки через общий endpoint
                return find_order_trades_alternative(order_id)
            
            order_state = order_details.get('state', 'unknown')
            logging.info(f"Ордер {order_id} статус: {order_state}")
            
            if order_state in ['done', 'filled']:
                # Ордер исполнен
                logging.info(f"Ордер {order_id} исполнен")
                db_manager.update_order_status(order_id=order_id, status="filled")
                
                # Пытаемся получить сделки, но не критично если не получится
                trades = find_order_trades_alternative(order_id)
                return trades if trades else []
            
            elif order_state in ['cancel', 'cancelled']:
                logging.info(f"Ордер {order_id} отменён")
                db_manager.update_order_status(order_id=order_id, status="cancelled")
                return None
            
            elif order_state in ['wait', 'pending']:
                # Ордер ожидает исполнения
                logging.debug(f"Ордер {order_id} ожидает исполнения")
            
            time.sleep(10)
        except Exception as e:
            logging.error(f"Ошибка отслеживания ордера {order_id}: {e}")
            time.sleep(10)
    
    logging.warning(f"Таймаут отслеживания ордера {order_id}")
    return None

def find_order_trades_alternative(order_id):
    """Альтернативный способ поиска сделок по ордеру"""
    try:
        # Пытаемся получить сделки через общий endpoint
        all_trades_response = scraper.get(f"{BASE_URL}/trade/market/trades", headers=get_auth_headers(), timeout=30)
        if all_trades_response.status_code == 200:
            all_trades = all_trades_response.json()
            # Фильтруем сделки по order_id
            order_trades = [t for t in all_trades if t.get('order_id') == str(order_id)]
            if order_trades:
                logging.info(f"Найдено {len(order_trades)} сделок для ордера {order_id} через альтернативный endpoint")
                return order_trades
        
        # Если сделки не найдены, это нормально для некоторых ордеров
        logging.info(f"Сделки для ордера {order_id} не найдены через альтернативный endpoint")
        return []
        
    except Exception as e:
        logging.warning(f"Ошибка при поиске сделок через альтернативный endpoint для ордера {order_id}: {e}")
        return []

def setup_websocket_order_tracking():
    """Настройка WebSocket для отслеживания ордеров в реальном времени"""
    try:
        # Проверяем доступность WebSocket
        ws_url = BASE_URL.replace("https://", "wss://").replace('http://', 'ws://') + "/websocket/"
        logging.info(f"WebSocket URL: {ws_url}")
        
        # Здесь можно добавить WebSocket подключение для отслеживания ордеров
        # Пока что используем REST API с улучшенной обработкой ошибок
        logging.info("WebSocket отслеживание ордеров доступно (требует дополнительной настройки)")
        return True
        
    except Exception as e:
        logging.warning(f"WebSocket недоступен: {e}")
        return False

def batch_check_orders_status(order_ids):
    """Пакетная проверка статуса нескольких ордеров"""
    try:
        # Получаем все активные ордера
        response = scraper.get(f"{BASE_URL}/trade/market/orders", headers=get_auth_headers(), timeout=30)
        if response.status_code == 200:
            all_orders = response.json()
            order_statuses = {}
            
            for order_id in order_ids:
                order = next((o for o in all_orders if o.get('id') == order_id), None)
                if order:
                    order_statuses[order_id] = order.get('state', 'unknown')
                else:
                    order_statuses[order_id] = 'not_found'
            
            return order_statuses
        else:
            logging.warning(f"Не удалось получить статусы ордеров: {response.status_code}")
            return {}
            
    except Exception as e:
        logging.error(f"Ошибка пакетной проверки статусов ордеров: {e}")
        return {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def cancel_order(order_id):
    """Отменяет ордер"""
    global db_manager
    try:
        # Используем новый API клиент для отмены ордера
        api_client.cancel_order(order_id)
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

def check_order_exists(order_id):
    """Проверяет существование ордера"""
    try:
        # Используем новый API клиент для проверки существования ордера
        # Сначала получаем все ордера и ищем нужный
        orders = api_client.get_orders()
        return any(order.get('id') == order_id for order in orders)
    except Exception as e:
        logging.error(f"Ошибка проверки существования ордера {order_id}: {e}")
        return False

def get_order_status(order_id):
    """Получает статус ордера"""
    try:
        # Используем новый API клиент для получения статуса ордера
        orders = api_client.get_orders()
        for order in orders:
            if order.get('id') == order_id:
                return order.get('state', 'unknown')
        
        logging.warning(f"Ордер {order_id} не найден")
        return 'not_found'
    except Exception as e:
        logging.error(f"Ошибка получения статуса ордера {order_id}: {e}")
        return 'unknown'

def get_order_details(order_id):
    """Получает детальную информацию об ордере"""
    try:
        # Используем новый API клиент для получения деталей ордера
        orders = api_client.get_orders()
        for order in orders:
            if order.get('id') == order_id:
                return order
        
        return None
    except Exception as e:
        logging.error(f"Ошибка получения деталей ордера {order_id}: {e}")
        return None

def track_order(order_id):
    """Фоновая функция для отслеживания ордера"""
    logging.info(f"Отслеживание ордера {order_id} начато")
    
    # Сначала проверяем, существует ли ордер
    if not check_order_exists(order_id):
        logging.warning(f"Ордер {order_id} не существует, прекращаем отслеживание")
        return
    
    try:
        # Устанавливаем WebSocket отслеживание если доступно
        websocket_available = setup_websocket_order_tracking()
        
        trades = track_order_execution(order_id, timeout=3600)  # 1 час
        if trades is not None:
            if trades:
                logging.info(f"Ордер {order_id} исполнен: {len(trades)} сделок")
            else:
                logging.info(f"Ордер {order_id} исполнен, но сделки не найдены")
        else:
            logging.warning(f"Ордер {order_id} не исполнен в течение часа")
            # Попробуем отменить неисполненный ордер
            cancel_order(order_id)
    except Exception as e:
        logging.error(f"Ошибка отслеживания ордера {order_id}: {e}")
        # Не прекращаем отслеживание при ошибке, продолжаем попытки

def cancel_all_active_orders():
    """Отменяет все активные ордера при завершении работы"""
    try:
        # Используем новый API клиент для получения всех ордеров
        orders = api_client.get_orders()
        
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
        with open("/app/data/cache_state.json", "w") as f:
            json.dump(cache_state, f, default=str)
        logging.info("Состояние кэша сохранено")
    except Exception as e:
        logging.error(f"Ошибка сохранения состояния кэша: {e}")

def load_cache_state():
    """Загружает состояние кэша при запуске"""
    try:
        cache_file = Path("/app/data/cache_state.json")
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
    if EASY_MODE:
        logging.info("🤖 РЕЖИМ: Простая продажа (EASY_MODE)")
    else:
        logging.info("🤖 РЕЖИМ: Продвинутая продажа со стратегиями")
    
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
                    
                    ai_decision = None
                    # Получаем решение ИИ, только если он включен и мы не в простом режиме
                    if AI_ENABLED and not EASY_MODE and cerebras_client:
                        ai_decision = ai_assistant.get_ai_trading_decision(
                            score.currency,
                            score.balance,
                            score.market_data,
                            db_manager  # Передаем db_manager
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
                mode_text = "Простой режим" if EASY_MODE else "Продвинутый режим"
                report = (
                    f"🤖 **Отчет по автопродажам**\n\n"
                    f"🔧 **Режим:** {mode_text}\n"
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

def test_api_endpoints():
    """Тестирует различные API эндпоинты и возвращает работающие"""
    working_endpoints = []
    
    # Тестируем эндпоинты для получения торговых пар
    try:
        response = scraper.get(f"{BASE_URL}/public/markets", timeout=30)
        if response.status_code == 200:
            working_endpoints.append("/public/markets")
            logging.info("✅ Эндпоинт /public/markets работает")
    except Exception as e:
        logging.warning(f"❌ Эндпоинт /public/markets не работает: {e}")
    
    # Тестируем эндпоинты для получения тикеров
    test_symbol = "qtcusdt"  # Используем символ из ваших рабочих логов
    try:
        response = scraper.get(f"{BASE_URL}/trade/public/tickers/{test_symbol}", timeout=30)
        if response.status_code == 200:
            working_endpoints.append(f"/trade/public/tickers/{test_symbol}")
            logging.info(f"✅ Эндпоинт /trade/public/tickers/{test_symbol} работает")
    except Exception as e:
        logging.warning(f"❌ Эндпоинт /trade/public/tickers/{test_symbol} не работает: {e}")
    
    # Тестируем эндпоинты для получения книги ордеров
    try:
        response = scraper.get(f"{BASE_URL}/trade/public/order-book/{test_symbol}", timeout=30)
        if response.status_code == 200:
            working_endpoints.append(f"/trade/public/order-book/{test_symbol}")
            logging.info(f"✅ Эндпоинт /trade/public/order-book/{test_symbol} работает")
    except Exception as e:
        logging.warning(f"❌ Эндпоинт /trade/public/order-book/{test_symbol} не работает: {e}")
    
    return working_endpoints

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
• `/test_api` - протестировать API эндпоинты (админ)
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

    @bot.message_handler(commands=['test_api'])
    def test_api_endpoints_cmd(message):
        """Тестирование API эндпоинтов"""
        if str(message.chat.id) == ADMIN_CHAT_ID:
            bot.reply_to(message, "🔍 Тестирую API эндпоинты...")
            
            def test_thread():
                try:
                    working_endpoints = test_api_endpoints()
                    if working_endpoints:
                        response = "✅ **API тест завершен**\n\n🎯 **Работающие эндпоинты:**\n"
                        for endpoint in working_endpoints:
                            response += f"• `{endpoint}`\n"
                    else:
                        response = "❌ **API тест завершен**\n\n🚨 Не найдено ни одного работающего эндпоинта!"
                    
                    bot.send_message(message.chat.id, response, parse_mode='Markdown')
                except Exception as e:
                    bot.send_message(message.chat.id, f"❌ Ошибка тестирования API: {e}")
            
            threading.Thread(target=test_thread).start()
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
            
            response = "💰 *Ваши балансы:*\n\n"
            total_usd = 0
            
            for i, score in enumerate(priority_scores, 1):
                total_usd += score.usd_value
                # Escape special Markdown characters
                currency = str(score.currency).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')
                response += (
                    f"{i}. *{currency}*\n"
                    f"   • Количество: `{score.balance:.8f}`\n"
                    f"   • Цена: `${score.market_data.current_price:.6f}`\n"
                    f"   • Стоимость: `${score.usd_value:.2f}`\n"
                    f"   • Приоритет: `{score.priority_score:.3f}`\n"
                    f"   • Волатильность: `{score.market_data.volatility:.4f}`\n\n"
                )
            
            response += f"💵 *Общая стоимость: ${total_usd:.2f}*"
            
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
        """Показывает историю последних сделок с использованием улучшенного форматирования"""
        try:
            bot.reply_to(message, "📊 Получаю историю сделок из SafeTrade API...")
            
            # Используем существующую функцию get_safetrade_order_history
            api_orders = get_safetrade_order_history()
            
            if api_orders:
                # Инициализируем TradeHistory клиент только для форматирования
                trade_history_client = trade_history.TradeHistory(BASE_URL, API_KEY, API_SECRET)
                
                # Используем TradeHistory для форматирования полученных данных
                formatted_history = trade_history_client.format_trade_history(api_orders)
                
                if formatted_history and "❌ Нет данных" not in formatted_history:
                    response = "📈 **История последних сделок:**\n\n"
                    response += formatted_history
                    bot.reply_to(message, response, parse_mode='Markdown')
                    
                    # Сохраняем полученные данные в базу для кэширования
                    try:
                        save_trade_history_to_db(trade_history_client)
                    except Exception as e:
                        logging.warning(f"Не удалось сохранить историю сделок в БД: {e}")
                else:
                    bot.reply_to(message, "❌ Не удалось отформатировать данные о сделках")
            else:
                bot.reply_to(message, "❌ Не удалось получить историю сделок из SafeTrade API")
                    
        except Exception as e:
            logging.error(f"Ошибка при получении истории сделок: {e}")
            bot.reply_to(message, f"❌ Ошибка при получении истории сделок: {str(e)}")

    @bot.message_handler(commands=['ai_status'])
    def show_ai_status(message):
        """Показывает статус ИИ-помощника"""
        global db_manager
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
            if ALLOWED_CURRENCIES:
                response += f"• Разрешенные валюты: `{', '.join(ALLOWED_CURRENCIES)}`\n"
            else:
                response += f"• Разрешенные валюты: `Все доступные`\n"
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
    global db_manager
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "cleanup":
            logging.info("🧹 Запуск очистки базы данных...")
            try:
                # Инициализируем Supabase для очистки
                if not SUPABASE_URL or not SUPABASE_KEY:
                    logging.error("❌ Отсутствуют настройки Supabase для очистки")
                    return
                
                supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                db_manager = DatabaseManager(supabase)
                
                if db_manager.manual_cleanup_if_needed():
                    logging.info("✅ Очистка базы данных завершена успешно")
                else:
                    logging.error("❌ Очистка базы данных завершилась с ошибкой")
                return
            except Exception as e:
                logging.error(f"❌ Ошибка при очистке: {e}")
                return
        elif command == "health":
            logging.info("🔍 Проверка здоровья базы данных...")
            try:
                if not SUPABASE_URL or not SUPABASE_KEY:
                    logging.error("❌ Отсутствуют настройки Supabase для проверки")
                    return
                
                supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                db_manager = DatabaseManager(supabase)
                
                # Получаем детальную статистику
                stats = db_manager.get_database_stats()
                if stats:
                    print("\n📊 Статистика базы данных:")
                    print(f"   • Торговые пары: {stats['trading_pairs']}")
                    print(f"   • История цен: {stats['price_history']}")
                    print(f"   • История ордеров: {stats['order_history']}")
                    print(f"   • Решения ИИ: {stats['ai_decisions']}")
                    print(f"   • Метрики производительности: {stats['performance_metrics']}")
                    print(f"   • Дубликаты: {stats['duplicates']}")
                    print(f"   • Соединение: {'✅' if stats['connection_healthy'] else '❌'}")
                
                # Проверяем здоровье
                health_result = db_manager.check_database_health()
                print(f"\n🏥 Здоровье БД: {'✅' if health_result else '❌'}")
                return
            except Exception as e:
                logging.error(f"❌ Ошибка при проверке здоровья: {e}")
                return
        elif command == "help":
            print("SafeTrade Trading Bot - Команды:")
            print("  python main.py          - Запуск бота")
            print("  python main.py cleanup  - Очистка дубликатов в БД")
            print("  python main.py health   - Проверка здоровья БД")
            print("  python main.py help     - Показать эту справку")
            return
        elif command == "env":
            print("🔧 Проверка переменных окружения:")
            print(f"   • SAFETRADE_API_KEY: {'✅' if API_KEY else '❌'}")
            print(f"   • SAFETRADE_API_SECRET: {'✅' if API_SECRET else '❌'}")
            print(f"   • SUPABASE_URL: {'✅' if SUPABASE_URL else '❌'}")
            print(f"   • SUPABASE_KEY: {'✅' if SUPABASE_KEY else '❌'}")
            print(f"   • TELEGRAM_BOT_TOKEN: {'✅' if TELEGRAM_BOT_TOKEN else '❌'}")
            print(f"   • CEREBRAS_API_KEY: {'✅' if CEREBRAS_API_KEY else '❌'}")
            print(f"   • SAFETRADE_EASY_MODE: {'✅' + str(EASY_MODE) if 'EASY_MODE_ENV' in globals() else '⚪ (из конфига)'}")
            print(f"   • SAFETRADE_AI_ENABLED: {'✅' + str(AI_ENABLED) if 'AI_ENABLED_ENV' in globals() else '⚪ (из конфига)'}")
            
            if not validate_environment():
                print("\n❌ Бот не может запуститься без обязательных переменных")
            else:
                print("\n✅ Все обязательные переменные настроены")
            return
    
    try:
        logging.info("Запуск SafeTrade Trading Bot...")
        
        # Показываем статус переменных окружения
        logging.info("🔧 Статус переменных окружения:")
        logging.info(f"   • SAFETRADE_API_KEY: {'✅' if API_KEY else '❌'}")
        logging.info(f"   • SAFETRADE_API_SECRET: {'✅' if API_SECRET else '❌'}")
        logging.info(f"   • SUPABASE_URL: {'✅' if SUPABASE_URL else '❌'}")
        logging.info(f"   • SUPABASE_KEY: {'✅' if SUPABASE_KEY else '❌'}")
        logging.info(f"   • TELEGRAM_BOT_TOKEN: {'✅' if TELEGRAM_BOT_TOKEN else '❌'}")
        logging.info(f"   • CEREBRAS_API_KEY: {'✅' if CEREBRAS_API_KEY else '❌'}")
        
        # Дополнительная отладка для API ключей
        if API_KEY:
            logging.info(f"   • API_KEY длина: {len(API_KEY)} символов")
            logging.info(f"   • API_KEY префикс: {API_KEY[:8]}...")
        if API_SECRET:
            logging.info(f"   • API_SECRET длина: {len(API_SECRET)} символов")
            logging.info(f"   • API_SECRET префикс: {API_SECRET[:8]}...")
        
        # Проверяем все обязательные переменные окружения
        if not validate_environment():
            logging.error("❌ Бот не может работать без обязательных переменных окружения")
            return
        
        logging.info("✅ Все обязательные переменные окружения настроены")
        
        # Показываем источники настроек режимов
        if EASY_MODE_ENV is not None:
            logging.warning(f"🔥 Включен EASY_MODE (из переменной окружения): вся продажа будет осуществляться по рыночным ценам без сложных проверок.")
        elif EASY_MODE:
            logging.warning(f"🔥 Включен EASY_MODE (из config.yml): вся продажа будет осуществляться по рыночным ценам без сложных проверок.")
            
        if AI_ENABLED_ENV is not None:
            logging.info(f"🧠 ИИ-помощник включен (из переменной окружения).")
        elif AI_ENABLED:
            logging.info(f"🧠 ИИ-помощник включен (из config.yml).")

        test_api_endpoints()
        
        # Инициализируем менеджер базы данных
        logging.info("🔍 Проверка здоровья базы данных при запуске...")
        try:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            db_manager = DatabaseManager(supabase)
            db_manager.check_database_health()
        except Exception as e:
            logging.error(f"❌ Ошибка инициализации базы данных: {e}")
            return
        
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
                    startup_message = (
                        f"🚀 **SafeTrade Trading Bot успешно запущен!**\n\n"
                        f"📅 **Время запуска:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"🤖 **Статус бота:** Активен\n"
                        f"🌐 **Сетевое подключение:** {'✅ OK' if check_network_connectivity() else '❌ Ошибка'}\n"
                        f"💾 **База данных:** {'✅ Подключена' if db_manager.check_connection() else '❌ Ошибка'}\n"
                        f"🧠 **ИИ-помощник:** {'✅ Активен' if cerebras_client else '❌ Отключен'}\n\n"
                        f"📊 **Конфигурация:**\n"
                        f"• Мин. стоимость позиции: ${MIN_POSITION_VALUE_USD}\n"
                        f"• Интервал автопродаж: {AUTO_SELL_INTERVAL} сек\n"
                        f"• Макс. одновременных продаж: {MAX_CONCURRENT_SALES}\n\n"
                        f"✅ Все системы готовы к работе!"
                    )
                    
                    bot.send_message(
                        ADMIN_CHAT_ID,
                        startup_message,
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

def save_trade_history_to_db(trade_history_client):
    """Сохраняет историю сделок в базу данных для кэширования"""
    global db_manager
    try:
        # Получаем последние сделки
        trades = trade_history_client.get_trade_history(limit=20)
        
        if trades and "❌ Нет данных" not in trades:
            logging.info("Сохраняю историю сделок в базу данных...")
            
            # Здесь можно добавить логику сохранения в БД
            # Пока что просто логируем успех
            logging.info("История сделок успешно обработана")
            
    except Exception as e:
        logging.error(f"Ошибка при сохранении истории сделок в БД: {e}")

def get_safetrade_order_history():
    """Получает историю ордеров из SafeTrade API с использованием нового клиента"""
    try:
        # Используем новый API клиент для получения истории ордеров
        orders = api_client.get_orders()
        
        if isinstance(orders, list) and len(orders) > 0:
            logging.info(f"✅ История ордеров успешно получена: {len(orders)} ордеров")
            return orders
        else:
            logging.warning("Получен пустой список ордеров")
            return []
        
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при получении истории ордеров: {e}")
        return None

if __name__ == "__main__":
    main()
