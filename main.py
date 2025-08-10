
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
import sqlite3
from pathlib import Path
import random
import math
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging
import sys
import signal
from threading import Lock, Semaphore
from tenacity import retry, stop_after_attempt, wait_exponential

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# --- НАСТРОЙКИ ---
load_dotenv()

# Загружаем токены и ID из переменных окружения
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")

# Supabase настройки
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# URL для пожертвований
DONATE_URL = "https://boosty.to/vokforever/donate"

# Убедимся, что секрет в байтовом представлении для hmac
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None
BASE_URL = "https://safe.trade/api/v2"

# Новые настройки из ТЗ
EXCLUDED_CURRENCIES = os.getenv("EXCLUDED_CURRENCIES", "USDT").split(",")
MIN_POSITION_VALUE_USD = float(os.getenv("MIN_POSITION_VALUE_USD", "1.0"))
MAX_CONCURRENT_SALES = int(os.getenv("MAX_CONCURRENT_SALES", "3"))
AUTO_SELL_INTERVAL = int(os.getenv("AUTO_SELL_INTERVAL", "3600"))

# Кэширование с locks для thread safety
cache_lock = Lock()
markets_cache = {
    "data": [],
    "last_update": None,
    "cache_duration": 14400  # 4 часа в секундах
}

prices_cache = {
    "data": {},
    "last_update": None,
    "cache_duration": 300  # 5 минут в секундах
}

orderbook_cache = {
    "data": {},
    "last_update": {},
    "cache_duration": 60  # 1 минута в секундах
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

@dataclass
class MarketData:
    symbol: str
    current_price: float
    volatility: float
    volume_24h: float
    bid_depth: float
    ask_depth: float
    spread: float

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

# Настройки для Cerebras API
CEREBRAS_MODEL = "qwen-3-235b-a22b-thinking-2507"
CEREBRAS_FREE_TIER_LIMITS = {
    "requests_per_min": 30,
    "input_tokens_per_min": 60000,
    "output_tokens_per_min": 8000,
    "daily_tokens": 1000000
}

# Счётчики для лимитов Cerebras
cerebras_usage = {
    "requests": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "daily_tokens": 0,
    "last_reset": time.time()
}

# Путь к файлу для хранения логов ИИ
AI_LOGS_PATH = Path("ai_decision_logs.json")
if not AI_LOGS_PATH.exists():
    with open(AI_LOGS_PATH, "w") as f:
        json.dump([], f)

# --- ИНИЦИАЛИЗАЦИЯ ---
scraper = cloudscraper.create_scraper()
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logging.warning("Supabase URL или KEY не указаны. Запись в базу данных будет отключена.")

cerebras_client = None
if CEREBRAS_API_KEY:
    cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)
else:
    logging.warning("CEREBRAS_API_KEY не указан. Функции ИИ будут отключены.")

# Инициализация локальной базы данных для аналитики
def init_local_db():
    """Инициализация локальной базы данных SQLite для аналитики"""
    conn = sqlite3.connect('trading_analytics.db')
    cursor = conn.cursor()
    
    # Создание таблицы для хранения исторических данных о ценах
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        symbol TEXT NOT NULL,
        price REAL NOT NULL,
        volume REAL,
        high REAL,
        low REAL
    )
    ''')
    
    # Создание таблицы для хранения истории ордеров
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS order_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        price REAL,
        total REAL,
        status TEXT NOT NULL
    )
    ''')
    
    # Создание таблицы для хранения решений ИИ
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ai_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        decision_type TEXT NOT NULL,
        decision_data TEXT NOT NULL,
        market_data TEXT,
        reasoning TEXT
    )
    ''')
    
    # Создание таблицы для хранения торговых пар
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trading_pairs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL UNIQUE,
        base_currency TEXT NOT NULL,
        quote_currency TEXT NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        last_updated TEXT
    )
    ''')
    
    conn.commit()
    conn.close()

init_local_db()

# Настраиваем клавиатуру с командами
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_all')
menu_markup.row('/history', '/ai_status')
menu_markup.row('/markets', '/donate')

# --- Graceful shutdown ---
def shutdown_handler(signum, frame):
    logging.info("Завершение бота...")
    # Здесь можно закрыть DB-соединения, сохранить состояние кэша и т.д.
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# --- Функции для работы с лимитами Cerebras ---
def check_cerebras_limits():
    """Проверяет, не превышены ли лимиты Cerebras API."""
    current_time = time.time()
    if current_time - cerebras_usage["last_reset"] > 86400:  # Сброс ежедневно
        cerebras_usage["daily_tokens"] = 0
        cerebras_usage["last_reset"] = current_time
    
    # Проверка минутных и ежедневных лимитов
    if (cerebras_usage["requests"] >= CEREBRAS_FREE_TIER_LIMITS["requests_per_min"] or
        cerebras_usage["input_tokens"] >= CEREBRAS_FREE_TIER_LIMITS["input_tokens_per_min"] or
        cerebras_usage["output_tokens"] >= CEREBRAS_FREE_TIER_LIMITS["output_tokens_per_min"] or
        cerebras_usage["daily_tokens"] >= CEREBRAS_FREE_TIER_LIMITS["daily_tokens"]):
        logging.warning("Достигнут лимит Cerebras API.")
        return False
    return True

def update_cerebras_usage(requests=1, input_tokens=0, output_tokens=0):
    """Обновляет счётчики использования."""
    cerebras_usage["requests"] += requests
    cerebras_usage["input_tokens"] += input_tokens
    cerebras_usage["output_tokens"] += output_tokens
    cerebras_usage["daily_tokens"] += input_tokens + output_tokens

# --- Функции для работы с API SafeTrade ---
def generate_signature(nonce, key, secret_bytes):
    """Генерирует подпись HMAC-SHA256."""
    string_to_sign = nonce + key
    return hmac.new(secret_bytes, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

def get_auth_headers():
    """Собирает все заголовки для аутентификации."""
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
    """
    Получает все доступные торговые пары с биржи
    Returns:
        list: Список торговых пар
    """
    global markets_cache
    
    with cache_lock:
        if (markets_cache["data"] and 
            markets_cache["last_update"] and 
            time.time() - markets_cache["last_update"] < markets_cache["cache_duration"]):
            return markets_cache["data"]
    
    try:
        path = "/public/markets"
        url = BASE_URL + path
        response = scraper.get(url)
        response.raise_for_status()
        markets = response.json()
        
        if isinstance(markets, list):
            # Фильтруем только пары с USDT
            usdt_markets = [
                market for market in markets 
                if market.get('quote_unit') == 'usdt' and 
                   market.get('base_unit', '').lower() not in [c.lower() for c in EXCLUDED_CURRENCIES]
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
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()
        
        for market in markets:
            cursor.execute('''
            INSERT OR REPLACE INTO trading_pairs 
            (symbol, base_currency, quote_currency, is_active, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                market.get('id', ''),
                market.get('base_unit', ''),
                market.get('quote_unit', ''),
                True,
                datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка при сохранении торговых пар: {e}")

def get_markets_from_db():
    """Получает торговые пары из базы данных"""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT symbol, base_currency, quote_currency, is_active
        FROM trading_pairs
        WHERE is_active = 1
        ''')
        
        markets = []
        for row in cursor.fetchall():
            markets.append({
                'id': row[0],
                'base_unit': row[1],
                'quote_unit': row[2],
                'active': row[3]
            })
        
        conn.close()
        return markets
    except Exception as e:
        logging.error(f"Ошибка при получении торговых пар из БД: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_sellable_balances():
    """
    Получает балансы всех криптовалют кроме USDT
    
    Returns:
        dict: {currency: balance} для всех альткоинов с балансом > 0
        None: если ошибка или нет продаваемых балансов
    """
    try:
        path = "/trade/account/balances/spot"
        url = BASE_URL + path
        headers = get_auth_headers()
        response = scraper.get(url, headers=headers)
        response.raise_for_status()
        balances = response.json()
        
        if not isinstance(balances, list):
            logging.warning("Некорректный формат балансов.")
            return None
        
        # Получаем доступные торговые пары
        markets = get_all_markets()
        available_currencies = {market.get('base_unit', '').lower() for market in markets}
        
        sellable_balances = {}
        for balance in balances:
            currency = balance.get('currency', '').upper()
            balance_amount = float(balance.get('balance', 0))
            
            # Пропускаем исключенные валюты и нулевые балансы
            if (currency.lower() in [c.lower() for c in EXCLUDED_CURRENCIES] or 
                balance_amount <= 0 or
                currency.lower() not in available_currencies):
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
        response = scraper.get(url)
        response.raise_for_status()
        ticker = response.json()
        
        if not isinstance(ticker, dict):
            logging.warning(f"Некорректный формат тикера для {symbol}.")
            return None
        
        price = float(ticker.get('last', 0))
        
        with cache_lock:
            prices_cache["data"][symbol] = price
            prices_cache["last_update"] = time.time()
        
        # Сохраняем в базу данных
        save_price_data(
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
        response = scraper.get(url)
        response.raise_for_status()
        orderbook = response.json()
        
        if not orderbook or not orderbook.get('bids') or not orderbook.get('asks'):
            logging.warning(f"Пустая книга ордеров для {symbol}.")
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
        logging.warning("Недостаточно данных для расчета волатильности.")
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
            logging.warning(f"Не удалось получить цену для {symbol}.")
            return None
        
        # Получаем книгу ордеров
        orderbook = get_orderbook(symbol)
        if not orderbook:
            logging.warning(f"Не удалось получить книгу ордеров для {symbol}.")
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
        response = scraper.get(url)
        response.raise_for_status()
        ticker = response.json()
        volume_24h = float(ticker.get('vol', 0))
        
        return MarketData(
            symbol=symbol.upper(),
            current_price=current_price,
            volatility=volatility,
            volume_24h=volume_24h,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            spread=spread
        )
    except Exception as e:
        logging.error(f"Ошибка при получении рыночных данных для {symbol}: {e}")
        return None

def prioritize_sales(balances_dict):
    """
    Сортирует валюты по приоритету продажи
    
    Args:
        balances_dict: {currency: balance}
        
    Returns:
        list: [PriorityScore] отсортированный по приоритету
    """
    priority_scores = []
    
    for currency, balance in balances_dict.items():
        try:
            if balance <= 0:
                continue  # Валидация: пропуск нулевых балансов
            
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
            # Весовые коэффициенты
            weight_value = 0.4      # Объем в USD
            weight_liquidity = 0.3   # Ликвидность
            weight_volatility = 0.2  # Волатильность (обратная)
            weight_spread = 0.1      # Спред (обратный)
            
            # Нормализуем показатели (0-1)
            value_score = min(usd_value / 1000, 1.0)  # Нормализуем к $1000
            liquidity_score = min(market_data.bid_depth / 10000, 1.0)  # Нормализуем к 10000
            volatility_score = 1 - min(market_data.volatility * 100, 1.0)  # Обратная волатильность
            spread_score = 1 - min(market_data.spread * 100, 1.0)  # Обратный спред
            
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
    
    if not check_cerebras_limits():
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
        - Объем торгов за последние 24 часа: {market_data.volume_24h}
        - Глубина книги ордеров (покупка): {market_data.bid_depth}
        - Глубина книги ордеров (продажа): {market_data.ask_depth}
        - Спред: {market_data.spread:.4f}
        
        Рекомендуемая базовая стратегия на основе размера позиции: {base_strategy}
        
        Доступные стратегии:
        1. Рыночный ордер (Market) - немедленное исполнение по текущей рыночной цене
        2. Лимитный ордер (Limit) - исполнение по указанной цене или лучше
        3. TWAP (Time-Weighted Average Price) - разделение ордера на части и исполнение через равные промежутки времени
        4. Iceberg (Айсберг) - отображение только небольшой части ордера, пока он исполняется
        5. Adaptive (Адаптивный) - динамический выбор стратегии на основе условий рынка
        
        Проанализируй рыночные условия и предложи лучшую стратегию для продажи {currency}. Учти размер позиции и условия рынка.
        
        В ответе укажи:
        1. Выбранную стратегию
        2. Параметры стратегии (если применимо)
        3. Обоснование выбора
        
        Ответ предоставь в формате JSON:
        {{
            "strategy": "market|limit|twap|iceberg|adaptive",
            "parameters": {{
                "price": 0.0,  // для лимитного ордера
                "duration_minutes": 60,  // для TWAP
                "chunks": 6,  // для TWAP
                "visible_amount": 0.1,  // для Iceberg
                "max_attempts": 20  // для Iceberg
            }},
            "reasoning": "Обоснование выбора стратегии"
        }}
        """
        
        # Отправляем запрос к ИИ
        response = cerebras_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": context,
                }
            ],
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
                
                # Сохраняем решение ИИ
                save_ai_decision(
                    decision_type="trading_strategy",
                    decision_data=decision,
                    market_data={
                        "currency": currency,
                        "balance": balance,
                        "usd_value": usd_value,
                        "current_price": market_data.current_price,
                        "volatility": market_data.volatility,
                        "volume_24h": market_data.volume_24h,
                        "bid_depth": market_data.bid_depth,
                        "ask_depth": market_data.ask_depth,
                        "spread": market_data.spread
                    },
                    reasoning=decision.get("reasoning", "")
                )
                
                # Обновляем использование (примерная оценка токенов)
                input_tokens = len(context) // 4
                output_tokens = len(ai_response) // 4
                update_cerebras_usage(1, input_tokens, output_tokens)
                
                return decision
            else:
                logging.error(f"Не удалось найти JSON в ответе ИИ: {ai_response}")
                return None
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка парсинга JSON из ответа ИИ: {e}")
            logging.debug(f"Ответ ИИ: {ai_response}")
            return None
    except Exception as e:
        logging.error(f"Ошибка при получении решения от ИИ: {e}")
        return None

def execute_twap_sell(market_symbol, total_amount, duration_minutes=60, chunks=6):
    """Исполнение TWAP продажи"""
    if total_amount <= 0 or chunks <= 0:
        logging.warning("Некорректные параметры для TWAP.")
        return 0, 0
    
    chunk_amount = total_amount / chunks
    interval_seconds = (duration_minutes * 60) / chunks
    sold_amount = 0
    total_received = 0
    
    for i in range(chunks):
        try:
            # Получаем текущую цену
            current_price = get_ticker_price(market_symbol)
            if not current_price:
                continue
            
            # Размещаем лимитный ордер чуть выше текущей цены
            limit_price = current_price * 1.001  # 0.1% выше рынка
            order_result = create_sell_order_safetrade(market_symbol, chunk_amount, "limit", limit_price)
            
            if order_result:
                order_id = order_result.split('ID ордера: ')[-1].split('\n')[0]
                if order_id:
                    # Отслеживаем исполнение ордера
                    trades = track_order_execution(order_id, timeout=300)  # 5 минут
                    if trades:
                        executed_amount = sum(float(t.get('amount', 0)) for t in trades)
                        executed_sum = sum(float(t.get('total', 0)) for t in trades)
                        sold_amount += executed_amount
                        total_received += executed_sum
                        
                        # Если ордер исполнился не полностью, добавляем остаток к следующему
                        remaining = chunk_amount - executed_amount
                        if remaining > 0 and i < chunks - 1:
                            chunk_amount += remaining
            
            # Ждем до следующего интервала
            if i < chunks - 1:
                time.sleep(interval_seconds)
        except Exception as e:
            logging.error(f"Ошибка в TWAP исполнении чанка {i + 1}: {e}")
    
    return sold_amount, total_received

def execute_iceberg_sell(market_symbol, total_amount, visible_amount=0.1, max_attempts=20):
    """Исполнение Iceberg продажи"""
    if total_amount <= 0 or visible_amount <= 0 or max_attempts <= 0:
        logging.warning("Некорректные параметры для Iceberg.")
        return 0, 0
    
    remaining = total_amount
    sold_amount = 0
    total_received = 0
    attempts = 0
    
    while remaining > 0 and attempts < max_attempts:
        try:
            # Определяем размер видимой части
            current_visible = min(visible_amount, remaining)
            
            # Получаем текущую цену и лучшую цену в книге ордеров
            orderbook = get_orderbook(market_symbol)
            if not orderbook or not orderbook.get('bids'):
                attempts += 1
                time.sleep(5)
                continue
            
            best_bid = float(orderbook['bids'][0][0])
            
            # Размещаем лимитный ордер на лучшей цене покупки
            order_result = create_sell_order_safetrade(market_symbol, current_visible, "limit", best_bid)
            
            if order_result:
                order_id = order_result.split('ID ордера: ')[-1].split('\n')[0]
                if order_id:
                    # Отслеживаем исполнение
                    trades = track_order_execution(order_id, timeout=60)
                    if trades:
                        executed_amount = sum(float(t.get('amount', 0)) for t in trades)
                        executed_sum = sum(float(t.get('total', 0)) for t in trades)
                        sold_amount += executed_amount
                        total_received += executed_sum
                        remaining -= executed_amount
            
            attempts += 1
            # Небольшая задержка между попытками
            time.sleep(5)
        except Exception as e:
            logging.error(f"Ошибка в Iceberg исполнении: {e}")
            attempts += 1
    
    return sold_amount, total_received

def execute_adaptive_sell(market_symbol, total_amount):
    """Адаптивная продажа на основе книги ордеров"""
    if total_amount <= 0:
        logging.warning("Некорректный amount для adaptive.")
        return 0, 0
    
    orderbook = get_orderbook(market_symbol)
    if not orderbook or not orderbook.get('bids'):
        logging.warning(f"Пустая книга ордеров для {market_symbol} в adaptive.")
        return 0, 0
    
    # Анализируем ликвидность на разных уровнях
    bids = orderbook.get('bids', [])
    
    # Группируем заявки по ценовым уровням
    price_levels = {}
    for bid in bids:
        price = float(bid[0])
        amount = float(bid[1])
        price_levels[price] = price_levels.get(price, 0) + amount
    
    # Сортируем по цене (от высокой к низкой)
    sorted_prices = sorted(price_levels.keys(), reverse=True)
    
    # Определяем оптимальные уровни для размещения
    remaining = total_amount
    placed_orders = []
    
    for price in sorted_prices:
        if remaining <= 0:
            break
        liquidity_at_price = price_levels[price]
        order_size = min(remaining, liquidity_at_price * 0.1)  # Берем не более 10% ликвидности на уровне
        
        if order_size > 0:
            # Размещаем ордер
            order_result = create_sell_order_safetrade(market_symbol, order_size, "limit", price)
            if order_result:
                order_id = order_result.split('ID ордера: ')[-1].split('\n')[0]
                placed_orders.append((order_id, order_size, price))
                remaining -= order_size
    
    # Если остались неразмещенные средства, используем рыночный ордер
    if remaining > 0:
        market_result = create_sell_order_safetrade(market_symbol, remaining, "market")
        if market_result:
            order_id = market_result.split('ID ордера: ')[-1].split('\n')[0]
            placed_orders.append((order_id, remaining, 'market'))
    
    # Отслеживаем исполнение всех ордеров
    sold_amount = 0
    total_received = 0
    
    for order_id, amount, price in placed_orders:
        trades = track_order_execution(order_id, timeout=600 if price != 'market' else 300)
        if trades:
            executed_amount = sum(float(t.get('amount', 0)) for t in trades)
            executed_sum = sum(float(t.get('total', 0)) for t in trades)
            sold_amount += executed_amount
            total_received += executed_sum
        else:
            # Отменяем неисполненный ордер (если лимитный)
            if price != 'market':
                cancel_order(order_id)
    
    return sold_amount, total_received

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def create_sell_order_safetrade(market_symbol, amount, order_type="market", price=None):
    """Создает ордер на продажу и возвращает отформатированный результат."""
    # Валидация входных данных
    if amount <= 0:
        logging.warning("Amount должен быть положительным.")
        return "❌ Amount должен быть положительным."
    if order_type == "limit" and (price is None or price <= 0):
        logging.warning("Для limit ордера price должен быть положительным.")
        return "❌ Для limit ордера price должен быть положительным."
    
    path = "/trade/market/orders"
    url = BASE_URL + path
    
    # Определяем валюты из символа
    base_currency = market_symbol.replace('usdt', '').upper()
    quote_currency = 'USDT'
    
    payload = {
        "market": market_symbol,
        "side": "sell",
        "type": order_type,
        "amount": str(amount)
    }
    
    if order_type == "limit" and price:
        payload["price"] = str(price)
    
    try:
        headers = get_auth_headers()
        response = scraper.post(url, headers=headers, json=payload)
        response.raise_for_status()
        order_details = response.json()
        
        order_id = order_details.get('id')
        order_amount = order_details.get('amount', amount)
        
        # Сохраняем данные об ордере в локальную базу
        save_order_data(
            order_id=order_id,
            timestamp=datetime.now().isoformat(),
            symbol=order_details.get('market', 'N/A'),
            side=order_details.get('side', 'N/A'),
            type=order_details.get('type', 'N/A'),
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
            error_message += f"\nОтвет сервера: `{e.response.text}`"
        logging.error(error_message)
        return error_message

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def track_order_execution(order_id, timeout=300):
    """Отслеживает исполнение ордера и возвращает trades."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            path = f"/trade/market/orders/{order_id}/trades"
            url = BASE_URL + path
            response = scraper.get(url, headers=get_auth_headers())
            response.raise_for_status()
            trades = response.json()
            if trades:
                return trades
            time.sleep(10)
        except Exception as e:
            logging.error(f"Ошибка отслеживания ордера {order_id}: {e}")
            time.sleep(10)
    logging.warning(f"Таймаут отслеживания ордера {order_id}.")
    return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def cancel_order(order_id):
    """Отменяет ордер."""
    try:
        path = f"/trade/market/orders/{order_id}/cancel"
        url = BASE_URL + path
        response = scraper.post(url, headers=get_auth_headers())
        response.raise_for_status()
        logging.info(f"Ордер {order_id} отменён.")
    except Exception as e:
        logging.error(f"Ошибка отмены ордера {order_id}: {e}")

def save_price_data(symbol, price, volume=None, high=None, low=None):
    """Сохраняет данные о цене в БД."""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO price_history (timestamp, symbol, price, volume, high, low)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), symbol, price, volume, high, low))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка сохранения цены: {e}")

def save_order_data(order_id, timestamp, symbol, side, type, amount, price, total, status):
    """Сохраняет данные об ордере в БД."""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO order_history (order_id, timestamp, symbol, side, type, amount, price, total, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, timestamp, symbol, side, type, amount, price, total, status))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка сохранения ордера: {e}")

def save_ai_decision(decision_type, decision_data, market_data, reasoning):
    """Сохраняет решение ИИ в БД и файл."""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO ai_decisions (timestamp, decision_type, decision_data, market_data, reasoning)
        VALUES (?, ?, ?, ?, ?)
        ''', (datetime.now().isoformat(), decision_type, json.dumps(decision_data), json.dumps(market_data), reasoning))
        conn.commit()
        conn.close()
        
        # Сохраняем в файл с lock для safety
        with cache_lock:
            with open(AI_LOGS_PATH, "r+") as f:
                logs = json.load(f)
                logs.append({
                    "timestamp": datetime.now().isoformat(),
                    "decision_type": decision_type,
                    "decision_data": decision_data,
                    "market_data": market_data,
                    "reasoning": reasoning
                })
                f.seek(0)
                json.dump(logs, f)
    except Exception as e:
        logging.error(f"Ошибка сохранения решения ИИ: {e}")

def track_order(order_id):
    """Фоновая функция для отслеживания ордера."""
    logging.info(f"Отслеживание ордера {order_id} начато.")
    # Здесь можно добавить дополнительную логику мониторинга

def invalidate_cache():
    """Инвалидация кэша после продажи."""
    with cache_lock:
        prices_cache["data"] = {}
        prices_cache["last_update"] = None
        orderbook_cache["data"] = {}
        orderbook_cache["last_update"] = {}
        logging.info("Кэш инвалидирован после продажи.")

def auto_sell_all_altcoins():
    """
    Главная функция автоматической продажи всех альткоинов
    
    Алгоритм:
    1. Получить все продаваемые балансы
    2. Проверить доступность торговых пар
    3. Приоритизировать продажи
    4. Для каждой валюты получить рекомендацию ИИ
    5. Исполнить продажу с выбранной стратегией
    6. Логировать результаты
    """
    auto_sell_enabled = os.getenv("AUTO_SELL_ENABLED", "true").lower() == "true"
    if not auto_sell_enabled:
        return
    
    try:
        # Отправляем уведомление о начале цикла
        bot.send_message(ADMIN_CHAT_ID, "🔄 Начат цикл автоматической продажи альткоинов...")
        
        # 1. Получаем все продаваемые балансы
        balances = get_sellable_balances()
        if not balances:
            bot.send_message(ADMIN_CHAT_ID, "✅ Не найдено альткоинов для продажи")
            return
        
        # 2. Приоритизируем продажи
        priority_list = prioritize_sales(balances)
        if not priority_list:
            bot.send_message(ADMIN_CHAT_ID, "❌ Не удалось рассчитать приоритеты для продажи")
            return
        
        # Формируем сообщение о найденных балансах
        balance_message = "🔄 Начат цикл автопродаж\n\nНайдено валют для продажи: {}\n\n".format(len(priority_list))
        total_usd_value = 0
        
        for item in priority_list:
            balance_message += f"💰 {item.currency}: {item.balance:.8f} (~${item.usd_value:.2f})\n"
            total_usd_value += item.usd_value
        
        balance_message += f"\nОбщая стоимость: ~${total_usd_value:.2f}"
        bot.send_message(ADMIN_CHAT_ID, balance_message)
        
        # 3. Обрабатываем каждую валюту
        successful_sales = []
        failed_sales = []
        
        for i, priority_item in enumerate(priority_list):
            with sales_sem:  # Ограничиваем concurrent продажи
                try:
                    currency = priority_item.currency
                    balance = priority_item.balance
                    market_data = priority_item.market_data
                    market_symbol = market_data.symbol.lower()
                    
                    # Получаем рекомендацию ИИ
                    ai_decision = get_ai_trading_decision(currency, balance, market_data)
                    
                    if ai_decision:
                        strategy = ai_decision.get("strategy")
                        parameters = ai_decision.get("parameters", {})
                        
                        # Выполняем выбранную стратегию
                        if strategy == "market":
                            sell_result = create_sell_order_safetrade(market_symbol, balance, "market")
                            successful_sales.append({
                                "currency": currency,
                                "strategy": "Market (ИИ)",
                                "result": sell_result
                            })
                            bot.send_message(ADMIN_CHAT_ID,
                                             f"🔄 *Автоматическая продажа ({currency}, Market, рекомендация ИИ)*\n\n{sell_result}",
                                             parse_mode='Markdown')
                        
                        elif strategy == "limit":
                            price = parameters.get("price", 0)
                            if price > 0:
                                sell_result = create_sell_order_safetrade(market_symbol, balance, "limit", price)
                                successful_sales.append({
                                    "currency": currency,
                                    "strategy": "Limit (ИИ)",
                                    "result": sell_result
                                })
                                bot.send_message(ADMIN_CHAT_ID,
                                                 f"🔄 *Автоматическая продажа ({currency}, Limit, рекомендация ИИ)*\n\n{sell_result}",
                                                 parse_mode='Markdown')
                            else:
                                # Если цена не указана, используем рыночный ордер
                                sell_result = create_sell_order_safetrade(market_symbol, balance, "market")
                                successful_sales.append({
                                    "currency": currency,
                                    "strategy": "Market (fallback)",
                                    "result": sell_result
                                })
                                bot.send_message(ADMIN_CHAT_ID,
                                                 f"🔄 *Автоматическая продажа ({currency}, Market, fallback из-за отсутствия цены)*\n\n{sell_result}",
                                                 parse_mode='Markdown')
                        
                        elif strategy == "twap":
                            duration = parameters.get("duration_minutes", 60)
                            chunks = parameters.get("chunks", 6)
                            sold_amount, total_received = execute_twap_sell(market_symbol, balance, duration, chunks)
                            avg_price = total_received / sold_amount if sold_amount > 0 else 0
                            message = (
                                f"🔄 *Автоматическая продажа ({currency}, TWAP, рекомендация ИИ)*\n\n"
                                f"*Продано:* `{sold_amount:.8f} {currency}`\n"
                                f"*Получено:* `{total_received:.8f} USDT`\n"
                                f"*Средняя цена:* `{avg_price:.8f} USDT`\n"
                                f"*Длительность:* `{duration} минут`\n"
                                f"*Количество частей:* `{chunks}`"
                            )
                            successful_sales.append({
                                "currency": currency,
                                "strategy": f"TWAP (ИИ)",
                                "result": message
                            })
                            bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                        
                        elif strategy == "iceberg":
                            visible_amount = parameters.get("visible_amount", 0.1)
                            max_attempts = parameters.get("max_attempts", 20)
                            sold_amount, total_received = execute_iceberg_sell(market_symbol, balance, visible_amount, max_attempts)
                            avg_price = total_received / sold_amount if sold_amount > 0 else 0
                            message = (
                                f"🔄 *Автоматическая продажа ({currency}, Iceberg, рекомендация ИИ)*\n\n"
                                f"*Продано:* `{sold_amount:.8f} {currency}`\n"
                                f"*Получено:* `{total_received:.8f} USDT`\n"
                                f"*Средняя цена:* `{avg_price:.8f} USDT`\n"
                                f"*Видимая часть:* `{visible_amount} {currency}`\n"
                                f"*Максимум попыток:* `{max_attempts}`"
                            )
                            successful_sales.append({
                                "currency": currency,
                                "strategy": f"Iceberg (ИИ)",
                                "result": message
                            })
                            bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                        
                        elif strategy == "adaptive":
                            sold_amount, total_received = execute_adaptive_sell(market_symbol, balance)
                            if sold_amount and total_received:
                                avg_price = total_received / sold_amount
                                message = (
                                    f"🔄 *Автоматическая продажа ({currency}, Adaptive, рекомендация ИИ)*\n\n"
                                    f"*Продано:* `{sold_amount:.8f} {currency}`\n"
                                    f"*Получено:* `{total_received:.8f} USDT`\n"
                                    f"*Средняя цена:* `{avg_price:.8f} USDT`"
                                )
                                successful_sales.append({
                                    "currency": currency,
                                    "strategy": f"Adaptive (ИИ)",
                                    "result": message
                                })
                                bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                            else:
                                failed_sales.append({
                                    "currency": currency,
                                    "error": "Adaptive strategy failed"
                                })
                        else:
                            # Неизвестная стратегия, fallback на market
                            sell_result = create_sell_order_safetrade(market_symbol, balance, "market")
                            successful_sales.append({
                                "currency": currency,
                                "strategy": "Market (fallback unknown strategy)",
                                "result": sell_result
                            })
                            bot.send_message(ADMIN_CHAT_ID,
                                             f"🔄 *Автоматическая продажа ({currency}, Market, fallback из-за неизвестной стратегии ИИ)*\n\n{sell_result}",
                                             parse_mode='Markdown')
                    else:
                        # Если ИИ недоступен или не дал решение, fallback на market
                        sell_result = create_sell_order_safetrade(market_symbol, balance, "market")
                        successful_sales.append({
                            "currency": currency,
                            "strategy": "Market (fallback AI unavailable)",
                            "result": sell_result
                        })
                        bot.send_message(ADMIN_CHAT_ID,
                                         f"🔄 *Автоматическая продажа ({currency}, Market, fallback из-за недоступности ИИ)*\n\n{sell_result}",
                                         parse_mode='Markdown')
                    
                    # Инвалидация кэша после продажи
                    invalidate_cache()
                    
                except Exception as e:
                    logging.error(f"Ошибка обработки {currency}: {e}")
                    failed_sales.append({
                        "currency": currency,
                        "error": str(e)
                    })
        
        # Логируем результаты
        if successful_sales:
            bot.send_message(ADMIN_CHAT_ID, f"✅ Успешные продажи: {len(successful_sales)}")
        if failed_sales:
            bot.send_message(ADMIN_CHAT_ID, f"❌ Ошибки продаж: {len(failed_sales)}")
    
    except Exception as e:
        logging.error(f"Критическая ошибка в auto_sell_all_altcoins: {e}")
        bot.send_message(ADMIN_CHAT_ID, f"❌ Критическая ошибка в цикле продаж: {e}")

# --- Запуск автоматического цикла ---
def schedule_auto_sell():
    auto_sell_all_altcoins()
    threading.Timer(AUTO_SELL_INTERVAL, schedule_auto_sell).start()

# --- Telegram-команды (пример) ---
@bot.message_handler(commands=['sell_all'])
def sell_all(message):
    auto_sell_all_altcoins()

if __name__ == "__main__":
    logging.info("Бот запущен.")
    schedule_auto_sell()
    bot.infinity_polling()
