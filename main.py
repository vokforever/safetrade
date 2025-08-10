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

# Кэширование
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
    print("[WARNING] Supabase URL или KEY не указаны. Запись в базу данных будет отключена.")

cerebras_client = None
if CEREBRAS_API_KEY:
    cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)
else:
    print("[WARNING] CEREBRAS_API_KEY не указан. Функции ИИ будут отключены.")

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

def get_all_markets():
    """
    Получает все доступные торговые пары с биржи
    Returns:
        list: Список торговых пар
    """
    global markets_cache
    
    # Проверяем кэш
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
            
            # Сохраняем в кэш
            markets_cache["data"] = usdt_markets
            markets_cache["last_update"] = time.time()
            
            # Сохраняем в базу данных
            save_markets_to_db(usdt_markets)
            
            return usdt_markets
    except Exception as e:
        print(f"Ошибка при получении торговых пар: {e}")
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
        print(f"Ошибка при сохранении торговых пар: {e}")

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
        print(f"Ошибка при получении торговых пар из БД: {e}")
        return []

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
            print(f"Найдены продаваемые балансы: {sellable_balances}")
            return sellable_balances
        
        return None
    except Exception as e:
        print(f"Ошибка при получении балансов: {e}")
        return None

def get_ticker_price(symbol):
    """Получает текущую цену для указанной торговой пары"""
    global prices_cache
    
    # Проверяем кэш
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
        
        if isinstance(ticker, dict):
            price = float(ticker.get('last', 0))
            
            # Сохраняем в кэш
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
        print(f"Ошибка получения цены для {symbol}: {e}")
    
    return None

def get_orderbook(symbol):
    """Получение книги ордеров для указанной пары"""
    global orderbook_cache
    
    # Проверяем кэш
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
        
        # Сохраняем в кэш
        orderbook_cache["data"][symbol] = orderbook
        orderbook_cache["last_update"][symbol] = time.time()
        
        return orderbook
    except Exception as e:
        print(f"Ошибка получения книги ордеров для {symbol}: {e}")
        return None

def calculate_volatility(orderbook):
    """Расчет волатильности на основе книги ордеров"""
    if not orderbook or not orderbook.get('bids') or not orderbook.get('asks'):
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
        print(f"Ошибка при расчете волатильности: {e}")
        return 0

def get_market_data(symbol):
    """Получает полные рыночные данные для указанной пары"""
    try:
        # Получаем текущую цену
        current_price = get_ticker_price(symbol)
        if not current_price:
            return None
        
        # Получаем книгу ордеров
        orderbook = get_orderbook(symbol)
        if not orderbook:
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
        print(f"Ошибка при получении рыночных данных для {symbol}: {e}")
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
            print(f"Ошибка при расчете приоритета для {currency}: {e}")
            continue
    
    # Сортируем по убыванию приоритета
    priority_scores.sort(key=lambda x: x.priority_score, reverse=True)
    
    return priority_scores

def get_ai_trading_decision(currency, balance, market_data):
    """Получение решения о торговле от ИИ для конкретной валюты"""
    if not cerebras_client:
        return None
    
    if not check_cerebras_limits():
        print("[WARNING] Достигнут лимит Cerebras API. Используется стандартная стратегия.")
        return None
    
    try:
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
                
                return decision
            else:
                print(f"[ERROR] Не удалось найти JSON в ответе ИИ: {ai_response}")
                return None
        except json.JSONDecodeError as e:
            print(f"[ERROR] Ошибка парсинга JSON из ответа ИИ: {e}")
            print(f"Ответ ИИ: {ai_response}")
            return None
    except Exception as e:
        print(f"[ERROR] Ошибка при получении решения от ИИ: {e}")
        return None

def execute_twap_sell(market_symbol, total_amount, duration_minutes=60, chunks=6):
    """Исполнение TWAP продажи"""
    chunk_amount = total_amount / chunks
    interval_seconds = (duration_minutes * 60) / chunks
    sold_amount = 0
    total_received = 0
    
    for i in range(chunks):
        try:
            # Получаем текущую цену
            current_price = get_ticker_price(market_symbol)
            if current_price:
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
            print(f"Ошибка в TWAP исполнении чанка {i + 1}: {e}")
    
    return sold_amount, total_received

def execute_iceberg_sell(market_symbol, total_amount, visible_amount=0.1, max_attempts=20):
    """Исполнение Iceberg продажи"""
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
            best_bid = float(orderbook['bids'][0][0]) if orderbook['bids'] else 0
            
            if best_bid:
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
            print(f"Ошибка в Iceberg исполнении: {e}")
            attempts += 1
    
    return sold_amount, total_received

def execute_adaptive_sell(market_symbol, total_amount):
    """Адаптивная продажа на основе книги ордеров"""
    orderbook = get_orderbook(market_symbol)
    if not orderbook:
        return None, None
    
    # Анализируем ликвидность на разных уровнях
    bids = orderbook.get('bids', [])
    if not bids:
        return None, None
    
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
        if price == 'market':
            # Для рыночного ордера ждем исполнения
            trades = track_order_execution(order_id, timeout=300)
            if trades:
                executed_amount = sum(float(t.get('amount', 0)) for t in trades)
                executed_sum = sum(float(t.get('total', 0)) for t in trades)
                sold_amount += executed_amount
                total_received += executed_sum
        else:
            # Для лимитных ордеров ждем или отменяем через время
            trades = track_order_execution(order_id, timeout=600)  # 10 минут
            if trades:
                executed_amount = sum(float(t.get('amount', 0)) for t in trades)
                executed_sum = sum(float(t.get('total', 0)) for t in trades)
                sold_amount += executed_amount
                total_received += executed_sum
            else:
                # Отменяем неисполненный ордер
                cancel_order(order_id)
    
    return sold_amount, total_received

def create_sell_order_safetrade(market_symbol, amount, order_type="market", price=None):
    """Создает ордер на продажу и возвращает отформатированный результат."""
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
        return error_message

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
        
        for i, priority_item in enumerate(priority_list[:MAX_CONCURRENT_SALES]):  # Ограничиваем количество одновременных продаж
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
                        # Неизвестная стратегия, используем рыночный ордер
                        sell_result = create_sell_order_safetrade(market_symbol, balance, "market")
                        successful_sales.append({
                            "currency": currency,
                            "strategy": "Market (неизвестная стратегия ИИ)",
                            "result": sell_result
                        })
                        bot.send_message(ADMIN_CHAT_ID,
                                         f"🔄 *Автоматическая продажа ({currency}, Market, неизвестная стратегия ИИ)*\n\n{sell_result}",
                                         parse_mode='Markdown')
                else:
                    # Если ИИ недоступен, используем адаптивную стратегию
                    sold_amount, total_received = execute_adaptive_sell(market_symbol, balance)
                    if sold_amount and total_received:
                        avg_price = total_received / sold_amount
                        message = (
                            f"🔄 *Автоматическая продажа ({currency}, Adaptive, без ИИ)*\n\n"
                            f"*Продано:* `{sold_amount:.8f} {currency}`\n"
                            f"*Получено:* `{total_received:.8f} USDT`\n"
                            f"*Средняя цена:* `{avg_price:.8f} USDT`"
                        )
                        successful_sales.append({
                            "currency": currency,
                            "strategy": "Adaptive (без ИИ)",
                            "result": message
                        })
                        bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                    else:
                        # Если адаптивная стратегия не сработала, используем простой рыночный ордер
                        sell_result = create_sell_order_safetrade(market_symbol, balance, "market")
                        successful_sales.append({
                            "currency": currency,
                            "strategy": "Market (fallback)",
                            "result": sell_result
                        })
                        bot.send_message(ADMIN_CHAT_ID, f"🔄 *Автоматическая продажа ({currency}, Market, fallback)*\n\n{sell_result}",
                                         parse_mode='Markdown')
                
                # Небольшая задержка между продажами разных валют
                if i < len(priority_list) - 1:
                    time.sleep(5)
                    
            except Exception as e:
                error_message = f"❌ Ошибка при продаже {priority_item.currency}: {e}"
                print(error_message)
                failed_sales.append({
                    "currency": priority_item.currency,
                    "error": str(e)
                })
                bot.send_message(ADMIN_CHAT_ID, error_message)
        
        # Формируем итоговое сообщение
        summary_message = "📊 *Итоги цикла автоматической продажи:*\n\n"
        summary_message += f"✅ Успешных продаж: {len(successful_sales)}\n"
        summary_message += f"❌ Ошибок: {len(failed_sales)}\n\n"
        
        if successful_sales:
            summary_message += "*Успешные продажи:*\n"
            for sale in successful_sales:
                summary_message += f"• {sale['currency']}: {sale['strategy']}\n"
        
        if failed_sales:
            summary_message += "\n*Ошибки:*\n"
            for sale in failed_sales:
                summary_message += f"• {sale['currency']}: {sale['error']}\n"
        
        bot.send_message(ADMIN_CHAT_ID, summary_message, parse_mode='Markdown')
        
    except Exception as e:
        error_message = f"❌ Критическая ошибка в цикле автоматической продажи: {e}"
        print(error_message)
        bot.send_message(ADMIN_CHAT_ID, error_message)

# --- Обработчики команд Telegram ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Обработчик команды /start с подробным описанием."""
    welcome_text = """
👋 *Добро пожаловать в улучшенный бот для управления биржей SafeTrade с поддержкой ИИ!*
Этот бот автоматически продает все ваши альткоины (кроме USDT) с использованием интеллектуальных стратегий.
Искусственный интеллект анализирует рыночные условия и выбирает оптимальную стратегию для каждой валюты.
*Доступные команды:*
✅ `/start` - Показать это приветственное сообщение и список команд.
💰 `/balance` - Показать все ваши ненулевые балансы на спотовом кошельке.
📉 `/sell_all` - Запустить автоматическую продажу всех альткоинов.
📊 `/history` - Показать историю ваших ордеров.
🤖 `/ai_status` - Показать статус ИИ и последние решения.
📈 `/markets` - Показать доступные торговые пары.
❤️ `/donate` - Поддержать автора бота.
Используйте кнопки внизу для быстрого доступа к командам.
"""
    bot.send_message(
        message.chat.id,
        text=welcome_text,
        parse_mode='Markdown',
        reply_markup=menu_markup
    )

@bot.message_handler(commands=['balance'])
def handle_balance(message):
    """Обработчик команды /balance."""
    bot.send_message(message.chat.id, "🔍 Запрашиваю балансы с SafeTrade...")
    
    try:
        headers = get_auth_headers()
        response = scraper.get(BASE_URL + "/trade/account/balances/spot", headers=headers)
        response.raise_for_status()
        balances = response.json()
        
        if isinstance(balances, list):
            non_zero_balances = [
                f"{b.get('currency', '').upper()}: `{b.get('balance', '0')}`"
                for b in balances if float(b.get('balance', 0)) > 0
            ]
            
            if non_zero_balances:
                balance_text = "Ваши ненулевые балансы на SafeTrade:\n\n" + "\n".join(non_zero_balances)
                
                # Добавляем информацию о продаваемых балансах
                sellable_balances = get_sellable_balances()
                if sellable_balances:
                    balance_text += "\n\n💰 *Доступно для автоматической продажи:*\n"
                    total_usd_value = 0
                    for currency, balance in sellable_balances.items():
                        market_symbol = f"{currency.lower()}usdt"
                        price = get_ticker_price(market_symbol)
                        if price:
                            usd_value = balance * price
                            total_usd_value += usd_value
                            balance_text += f"• {currency}: `{balance:.8f}` (~${usd_value:.2f})\n"
                    
                    balance_text += f"\n*Общая стоимость: ~${total_usd_value:.2f}*"
                
                bot.send_message(message.chat.id, balance_text, parse_mode='Markdown')
            else:
                bot.send_message(message.chat.id, "У вас нет ненулевых балансов на SafeTrade.")
        else:
            bot.send_message(message.chat.id, f"Ошибка: получен неожиданный формат данных от SafeTrade: {balances}")
    except Exception as e:
        error_message = f"❌ Ошибка при получении балансов с SafeTrade: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nОтвет сервера: {e.response.text}"
        bot.send_message(message.chat.id, error_message)

@bot.message_handler(commands=['sell_all'])
def handle_sell_all(message):
    """Обработчик команды /sell_all."""
    if message.chat.id != int(ADMIN_CHAT_ID):
        bot.send_message(message.chat.id, "❌ Эта команда доступна только администратору")
        return
    
    bot.send_message(message.chat.id, "🔄 Запускаю автоматическую продажу всех альткоинов...")
    
    # Запускаем в отдельном потоке, чтобы не блокировать бота
    threading.Thread(target=auto_sell_all_altcoins, daemon=True).start()

@bot.message_handler(commands=['markets'])
def handle_markets(message):
    """Обработчик команды /markets."""
    bot.send_message(message.chat.id, "🔍 Запрашиваю доступные торговые пары...")
    
    markets = get_all_markets()
    if markets:
        markets_text = f"📊 *Доступные торговые пары с USDT:* ({len(markets)} пар)\n\n"
        
        for market in markets[:20]:  # Показываем первые 20 пар
            symbol = market.get('id', '').upper()
            base_currency = market.get('base_unit', '').upper()
            markets_text += f"• {symbol} ({base_currency}/USDT)\n"
        
        if len(markets) > 20:
            markets_text += f"\n... и еще {len(markets) - 20} пар"
        
        bot.send_message(message.chat.id, markets_text, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "❌ Не удалось получить список торговых пар")

# --- Основной цикл бота ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print(
            "[CRITICAL] Не все переменные окружения установлены! Проверьте SAFETRADE_API_KEY, SAFETRADE_API_SECRET, TELEGRAM_BOT_TOKEN и ADMIN_CHAT_ID в файле .env"
        )
    else:
        print("Улучшенный бот SafeTrade с поддержкой ИИ запущен...")
        
        # Синхронизация отсутствующих записей при старте
        if supabase:
            print("🔄 Запускаю синхронизацию записей о продажах...")
            sync_missing_sales()
        
        # Запускаем поток для автоматической продажи альткоинов
        auto_sell_thread = threading.Thread(target=auto_sell_all_altcoins, daemon=True)
        auto_sell_thread.start()
        print("🔄 Запущен автоматический режим продажи альткоинов")
        
        try:
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ai_status = "с поддержкой ИИ" if cerebras_client else "без поддержки ИИ"
            bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *Улучшенный бот SafeTrade успешно запущен!*\n\n*Время запуска:* `{start_time}`\n*Режим:* {ai_status}\nОжидаю команды...\n\n🔄 *Автоматическая продажа альткоинов включена*",
                parse_mode='Markdown'
            )
            print(f"Уведомление о запуске отправлено администратору (Chat ID: {ADMIN_CHAT_ID})")
        except Exception as e:
            print(f"[WARNING] Не удалось отправить уведомление о запуске администратору. Ошибка: {e}")
        
        bot.infinity_polling()
