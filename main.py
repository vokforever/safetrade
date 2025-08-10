import time
import hmac
import hashlib
import json
import os
import telebot
from telebot import types
from dotenv import load_dotenv
import cloudscraper
from datetime import datetime
import threading
from supabase import create_client, Client
from cerebras.cloud.sdk import Cerebras
import requests
import sqlite3
from pathlib import Path

# --- НАСТРОЙКИ ---
load_dotenv()
# Загружаем токены и ID из переменных окружения
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # ID администратора для уведомлений
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")  # API ключ для Cerebras

# Supabase настройки
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# URL для пожертвований
DONATE_URL = "https://boosty.to/vokforever/donate"

# Убедимся, что секрет в байтовом представлении для hmac
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None
BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
TABLE_PREFIX = "miner_"

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
# Создаем экземпляр скрейпера для обхода защиты Cloudflare
scraper = cloudscraper.create_scraper()

# Инициализация бота Telegram
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Инициализация Supabase клиента
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("[WARNING] Supabase URL или KEY не указаны. Запись в базу данных будет отключена.")

# Инициализация Cerebras клиента
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

    conn.commit()
    conn.close()


init_local_db()

# Настраиваем клавиатуру с командами
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_qtc')
menu_markup.row('/history', '/ai_status')
menu_markup.row('/donate')


# --- Функции для работы с локальной базой данных ---
def save_price_data(symbol, price, volume=None, high=None, low=None):
    """Сохранение данных о ценах в локальную базу данных"""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()

        timestamp = datetime.now().isoformat()

        cursor.execute('''
        INSERT INTO price_history (timestamp, symbol, price, volume, high, low)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (timestamp, symbol, price, volume, high, low))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при сохранении данных о ценах: {e}")
        return False


def save_order_data(order_id, timestamp, symbol, side, type_, amount, price=None, total=None, status=None):
    """Сохранение данных об ордерах в локальную базу данных"""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()

        cursor.execute('''
        INSERT INTO order_history (order_id, timestamp, symbol, side, type, amount, price, total, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, timestamp, symbol, side, type_, amount, price, total, status))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при сохранении данных об ордере: {e}")
        return False


def save_ai_decision(decision_type, decision_data, market_data=None, reasoning=None):
    """Сохранение решений ИИ в локальную базу данных и JSON файл"""
    try:
        # Сохранение в SQLite
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()

        timestamp = datetime.now().isoformat()

        cursor.execute('''
        INSERT INTO ai_decisions (timestamp, decision_type, decision_data, market_data, reasoning)
        VALUES (?, ?, ?, ?, ?)
        ''', (timestamp, decision_type, json.dumps(decision_data),
              json.dumps(market_data) if market_data else None, reasoning))

        conn.commit()
        conn.close()

        # Сохранение в JSON файл
        with open(AI_LOGS_PATH, "r") as f:
            logs = json.load(f)

        new_log_entry = {
            "timestamp": timestamp,
            "decision_type": decision_type,
            "decision_data": decision_data,
            "market_data": market_data,
            "reasoning": reasoning
        }

        logs.append(new_log_entry)

        with open(AI_LOGS_PATH, "w") as f:
            json.dump(logs, f, indent=2)

        return True
    except Exception as e:
        print(f"Ошибка при сохранении решения ИИ: {e}")
        return False


def get_price_history(symbol, limit=100):
    """Получение истории цен из локальной базы данных"""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT timestamp, price, volume, high, low
        FROM price_history
        WHERE symbol = ?
        ORDER BY timestamp DESC
        LIMIT ?
        ''', (symbol, limit))

        data = cursor.fetchall()
        conn.close()

        return [
            {
                "timestamp": row[0],
                "price": row[1],
                "volume": row[2],
                "high": row[3],
                "low": row[4]
            }
            for row in data
        ]
    except Exception as e:
        print(f"Ошибка при получении истории цен: {e}")
        return []


def get_recent_ai_decisions(limit=10):
    """Получение последних решений ИИ из локальной базы данных"""
    try:
        conn = sqlite3.connect('trading_analytics.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT timestamp, decision_type, decision_data, market_data, reasoning
        FROM ai_decisions
        ORDER BY timestamp DESC
        LIMIT ?
        ''', (limit,))

        data = cursor.fetchall()
        conn.close()

        return [
            {
                "timestamp": row[0],
                "decision_type": row[1],
                "decision_data": json.loads(row[2]) if row[2] else None,
                "market_data": json.loads(row[3]) if row[3] else None,
                "reasoning": row[4]
            }
            for row in data
        ]
    except Exception as e:
        print(f"Ошибка при получении решений ИИ: {e}")
        return []


# --- Функции для работы с Supabase ---
def check_sale_record_exists(order_id):
    """Проверяет, существует ли запись о продаже в Supabase."""
    if not supabase:
        return False
    try:
        table_name = f"{TABLE_PREFIX}sales"
        response = supabase.table(table_name).select("*").eq("order_id", order_id).execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"Ошибка при проверке записи о продаже {order_id}: {e}")
        return False


def insert_sale_record(order_id, amount, total_sum, avg_price, executed_time):
    """Записывает данные о продаже в Supabase."""
    if not supabase:
        print("[WARNING] Supabase не инициализирован. Запись невозможна.")
        return False
    try:
        table_name = f"{TABLE_PREFIX}sales"
        sale_data = {
            "order_id": order_id,
            "currency_sold": CURRENCY_TO_SELL,
            "currency_bought": CURRENCY_TO_BUY,
            "amount_sold": float(amount),
            "total_received": float(total_sum),
            "avg_price": float(avg_price),
            "executed_at": executed_time,
            "created_at": datetime.now().isoformat()
        }
        response = supabase.table(table_name).insert(sale_data).execute()
        print(f"✅ Запись о продаже {order_id} успешно добавлена в Supabase")
        return True
    except Exception as e:
        print(f"❌ Ошибка при записи продажи {order_id} в Supabase: {e}")
        return False


def sync_missing_sales():
    """Синхронизирует отсутствующие записи о продажах при старте программы."""
    if not supabase:
        print("[WARNING] Supabase не инициализирован. Синхронизация невозможна.")
        return
    print("🔍 Проверка отсутствующих записей о продажах...")
    try:
        # Получаем историю ордеров
        orders = get_order_history(limit=50)  # Увеличиваем лимит для более глубокой проверки
        if orders and isinstance(orders, list):
            synced_count = 0
            for order in orders:
                order_id = order.get('id')
                if order_id and order.get('state') == 'done' and order.get('side') == 'sell':
                    # Проверяем, есть ли запись в Supabase
                    if not check_sale_record_exists(order_id):
                        # Получаем детальную информацию о сделках
                        trades = get_order_trades(order_id)
                        if trades and isinstance(trades, list) and len(trades) > 0:
                            total_amount = sum(float(trade.get('amount', 0)) for trade in trades)
                            total_sum = sum(float(trade.get('total', 0)) for trade in trades)
                            avg_price = total_sum / total_amount if total_amount > 0 else 0
                            # Форматируем время исполнения
                            created_at = order.get('created_at', 'N/A')
                            try:
                                dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                                executed_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                            except:
                                executed_time = created_at
                            # Записываем в Supabase
                            if insert_sale_record(order_id, total_amount, total_sum, avg_price, executed_time):
                                synced_count += 1
            if synced_count > 0:
                print(f"✅ Синхронизировано {synced_count} записей о продажах")
                try:
                    bot.send_message(
                        ADMIN_CHAT_ID,
                        f"✅ *Синхронизация завершена!*\n\nДобавлено {synced_count} записей о продажах в базу данных.",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    print(f"Ошибка отправки уведомления о синхронизации: {e}")
            else:
                print("✅ Все записи о продажах уже синхронизированы")
    except Exception as e:
        print(f"❌ Ошибка при синхронизации продаж: {e}")


# --- Функции API SafeTrade ---
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


def get_balances_safetrade():
    """Получает и форматирует ненулевые балансы."""
    path = "/trade/account/balances/spot"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        response = scraper.get(url, headers=headers)
        response.raise_for_status()
        balances = response.json()
        if isinstance(balances, list):
            non_zero_balances = [
                f"{b.get('currency', '').upper()}: `{b.get('balance', '0')}`"
                for b in balances if float(b.get('balance', 0)) > 0
            ]
            if non_zero_balances:
                return "Ваши ненулевые балансы на SafeTrade:\n\n" + "\n".join(non_zero_balances)
            else:
                return "У вас нет ненулевых балансов на SafeTrade."
        else:
            return f"Ошибка: получен неожиданный формат данных от SafeTrade: {balances}"
    except Exception as e:
        error_message = f"❌ Ошибка при получении балансов с SafeTrade: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nОтвет сервера: {e.response.text}"
        return error_message


def create_sell_order_safetrade(amount, order_type="market", price=None):
    """Создает ордер на продажу и возвращает отформатированный результат."""
    path = "/trade/market/orders"
    url = BASE_URL + path

    payload = {
        "market": MARKET_SYMBOL,
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
            f"*Заявленный объем:* `{order_amount} {CURRENCY_TO_SELL}`\n"
            f"*ID ордера:* `{order_id}`"
        )
    except Exception as e:
        error_message = f"❌ Ошибка при создании ордера на продажу на SafeTrade: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nОтвет сервера: `{e.response.text}`"
        return error_message


def get_order_info(order_id):
    """Получает информацию о конкретном ордере."""
    path = f"/trade/market/orders/{order_id}"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        response = scraper.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении информации об ордере {order_id}: {e}")
        return None


def get_order_trades(order_id):
    """Получает сделки по конкретному ордеру, фильтруя общую историю сделок."""
    path = "/trade/market/trades"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        params = {"order_id": str(order_id)}
        response = scraper.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении сделок по ордеру {order_id}: {e}")
        return []


def get_order_history(limit=10):
    """Получает историю ордеров с биржи."""
    path = "/trade/market/orders"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        params = {"market": MARKET_SYMBOL, "limit": limit, "state": "done"}
        response = scraper.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении истории ордеров: {e}")
        return []


def get_ticker_price():
    """Получает текущую цену QTC/USDT"""
    path = f"/trade/market/tickers/{MARKET_SYMBOL}"
    url = BASE_URL + path
    try:
        response = scraper.get(url)
        response.raise_for_status()
        ticker = response.json()
        price = float(ticker.get('last', 0))

        # Сохраняем данные о цене в локальную базу
        save_price_data(
            symbol=MARKET_SYMBOL.upper(),
            price=price,
            volume=float(ticker.get('vol', 0)) if ticker.get('vol') else None,
            high=float(ticker.get('high', 0)) if ticker.get('high') else None,
            low=float(ticker.get('low', 0)) if ticker.get('low') else None
        )

        return price
    except Exception as e:
        print(f"Ошибка получения цены: {e}")
        return None


def get_orderbook():
    """Получение книги ордеров"""
    path = f"/trade/market/orderbook/{MARKET_SYMBOL}"
    url = BASE_URL + path
    try:
        response = scraper.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка получения книги ордеров: {e}")
        return None


def get_recent_trades(limit=50):
    """Получение недавних сделок"""
    path = f"/trade/market/trades"
    url = BASE_URL + path
    try:
        params = {"market": MARKET_SYMBOL, "limit": limit}
        response = scraper.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка получения недавних сделок: {e}")
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


def calculate_optimal_order_size(balance, orderbook):
    """Расчет оптимального размера ордера на основе ликвидности"""
    if not orderbook or not orderbook.get('bids'):
        return balance

    try:
        # Берем не более 5% от ликвидности на лучших 5 уровнях
        total_liquidity = sum(float(bid[1]) for bid in orderbook['bids'][:5])
        optimal_size = min(balance, total_liquidity * 0.05)
        return optimal_size
    except Exception as e:
        print(f"Ошибка при расчете оптимального размера ордера: {e}")
        return balance


def track_order(order_id):
    """Отслеживает статус ордера и уведомляет о его исполнении."""
    max_attempts = 30
    check_interval = 10
    for _ in range(max_attempts):
        time.sleep(check_interval)
        order_info = get_order_info(order_id)
        if not order_info:
            continue
        if order_info.get('state') == 'done':
            trades = get_order_trades(order_id)
            if trades:
                total_amount = sum(float(trade.get('amount', 0)) for trade in trades)
                total_sum = sum(float(trade.get('total', 0)) for trade in trades)
                avg_price = total_sum / total_amount if total_amount > 0 else 0
                executed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Обновляем статус ордера в локальной базе данных
                try:
                    conn = sqlite3.connect('trading_analytics.db')
                    cursor = conn.cursor()
                    cursor.execute('''
                    UPDATE order_history
                    SET status = ?, total = ?
                    WHERE order_id = ?
                    ''', ('done', total_sum, order_id))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"Ошибка при обновлении статуса ордера: {e}")

                # Записываем данные о продаже в Supabase
                if supabase:
                    insert_sale_record(order_id, total_amount, total_sum, avg_price, executed_time)

                message = (
                    f"✅ *Ордер исполнен!*\n\n"
                    f"*ID ордера:* `{order_id}`\n"
                    f"*Пара:* `{MARKET_SYMBOL.upper()}`\n"
                    f"*Продано:* `{total_amount:.8f} {CURRENCY_TO_SELL}`\n"
                    f"*Получено:* `{total_sum:.8f} {CURRENCY_TO_BUY}`\n"
                    f"*Средняя цена:* `{avg_price:.8f} {CURRENCY_TO_BUY}`\n"
                    f"*Время исполнения:* `{executed_time}`"
                )
                try:
                    bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                except Exception as e:
                    print(f"Ошибка отправки уведомления: {e}")
                return
        elif order_info.get('state') == 'cancel':
            # Обновляем статус ордера в локальной базе данных
            try:
                conn = sqlite3.connect('trading_analytics.db')
                cursor = conn.cursor()
                cursor.execute('''
                UPDATE order_history
                SET status = ?
                WHERE order_id = ?
                ''', ('cancel', order_id))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Ошибка при обновлении статуса ордера: {e}")
            return
    print(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток")


# --- Функции для работы с ИИ ---
def check_cerebras_limits():
    """Проверка лимитов Cerebras API"""
    # В реальном приложении здесь должна быть проверка текущего использования API
    # Для упрощения всегда возвращаем True
    return True


def get_ai_trading_decision(qtc_balance, market_data):
    """Получение решения о торговле от ИИ"""
    if not cerebras_client:
        return None

    if not check_cerebras_limits():
        print("[WARNING] Достигнут лимит Cerebras API. Используется стандартная стратегия.")
        return None

    try:
        # Формируем контекст для ИИ
        context = f"""
        Ты - торговый ИИ-ассистент для криптовалютной биржи SafeTrade. Твоя задача - проанализировать текущие рыночные условия и предложить оптимальную стратегию для продажи {qtc_balance} {CURRENCY_TO_SELL} за {CURRENCY_TO_BUY}.

        Текущие рыночные данные:
        - Баланс {CURRENCY_TO_SELL}: {qtc_balance}
        - Текущая цена: {market_data.get('current_price', 'N/A')}
        - Волатильность рынка: {market_data.get('volatility', 'N/A')}
        - Объем торгов за последние 24 часа: {market_data.get('volume_24h', 'N/A')}
        - История цен за последние 24 часа: {market_data.get('price_history', 'N/A')}
        - Глубина книги ордеров (покупка): {market_data.get('bid_depth', 'N/A')}
        - Глубина книги ордеров (продажа): {market_data.get('ask_depth', 'N/A')}
        - Недавние сделки: {market_data.get('recent_trades', 'N/A')}

        Доступные стратегии:
        1. Рыночный ордер (Market) - немедленное исполнение по текущей рыночной цене
        2. Лимитный ордер (Limit) - исполнение по указанной цене или лучше
        3. TWAP (Time-Weighted Average Price) - разделение ордера на части и исполнение через равные промежутки времени
        4. Iceberg (Айсберг) - отображение только небольшой части ордера, пока он исполняется

        Проанализируй рыночные условия и предложи лучшую стратегию для продажи {CURRENCY_TO_SELL}. В ответе укажи:
        1. Выбранную стратегию
        2. Параметры стратегии (если применимо)
        3. Обоснование выбора

        Ответ предоставь в формате JSON:
        {{
            "strategy": "market|limit|twap|iceberg",
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
            max_completion_tokens=4000,  # Увеличиваем лимит для получения полного ответа
        )

        # Парсим ответ
        ai_response = response.choices[0].message.content

        # Ищем JSON в ответе
        try:
            # Пытаемся найти JSON в ответе
            start_idx = ai_response.find('{')
            end_idx = ai_response.rfind('}') + 1

            if start_idx != -1 and end_idx != -1:
                json_str = ai_response[start_idx:end_idx]
                decision = json.loads(json_str)

                # Сохраняем решение ИИ
                save_ai_decision(
                    decision_type="trading_strategy",
                    decision_data=decision,
                    market_data=market_data,
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


def execute_twap_sell(total_amount, duration_minutes=60, chunks=6):
    """Исполнение TWAP продажи"""
    chunk_amount = total_amount / chunks
    interval_seconds = (duration_minutes * 60) / chunks

    sold_amount = 0
    total_received = 0

    for i in range(chunks):
        try:
            # Получаем текущую цену
            current_price = get_ticker_price()
            if current_price:
                # Размещаем лимитный ордер чуть выше текущей цены
                limit_price = current_price * 1.001  # 0.1% выше рынка

                order_result = create_sell_order_safetrade(chunk_amount, "limit", limit_price)
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


def execute_iceberg_sell(total_amount, visible_amount=0.1, max_attempts=20):
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
            orderbook = get_orderbook()
            best_bid = float(orderbook['bids'][0][0]) if orderbook['bids'] else 0

            if best_bid:
                # Размещаем лимитный ордер на лучшей цене покупки
                order_result = create_sell_order_safetrade(current_visible, "limit", best_bid)

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


def execute_adaptive_sell(total_amount):
    """Адаптивная продажа на основе книги ордеров"""
    orderbook = get_orderbook()
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
            order_result = create_sell_order_safetrade(order_size, "limit", price)
            if order_result:
                order_id = order_result.split('ID ордера: ')[-1].split('\n')[0]
                placed_orders.append((order_id, order_size, price))
                remaining -= order_size

    # Если остались неразмещенные средства, используем рыночный ордер
    if remaining > 0:
        market_result = create_sell_order_safetrade(remaining, "market")
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


def track_order_execution(order_id, timeout=60):
    """Отслеживает исполнение ордера и возвращает сделки"""
    start_time = time.time()

    while time.time() - start_time < timeout:
        order_info = get_order_info(order_id)
        if not order_info:
            continue

        if order_info.get('state') == 'done':
            return get_order_trades(order_id)
        elif order_info.get('state') == 'cancel':
            return None

        time.sleep(2)

    return None


def cancel_order(order_id):
    """Отменяет ордер"""
    path = f"/trade/market/orders/{order_id}"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        response = scraper.delete(url, headers=headers)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Ошибка при отмене ордера {order_id}: {e}")
        return False


def auto_sell_qtc_advanced():
    """Улучшенная авто-продажа с использованием ИИ для выбора стратегии"""
    auto_sell_enabled = os.getenv("AUTO_SELL_ENABLED", "true").lower() == "true"
    if not auto_sell_enabled:
        return

    while True:
        try:
            # Получаем баланс
            headers = get_auth_headers()
            response = scraper.get(BASE_URL + "/trade/account/balances/spot", headers=headers)
            response.raise_for_status()
            balances = response.json()

            qtc_balance = 0.0
            if isinstance(balances, list):
                for balance in balances:
                    if balance.get("currency", "").upper() == CURRENCY_TO_SELL:
                        qtc_balance = float(balance.get("balance", 0))
                        break

            if qtc_balance <= 0:
                time.sleep(3600)
                continue

            # Собираем рыночные данные для анализа
            market_data = {
                "current_price": get_ticker_price(),
                "volatility": None,
                "volume_24h": None,
                "price_history": None,
                "bid_depth": None,
                "ask_depth": None,
                "recent_trades": None
            }

            # Получаем дополнительные данные
            orderbook = get_orderbook()
            if orderbook:
                market_data["volatility"] = calculate_volatility(orderbook)

                # Рассчитываем глубину книги ордеров
                market_data["bid_depth"] = sum(float(bid[1]) for bid in orderbook.get('bids', [])[:10])
                market_data["ask_depth"] = sum(float(ask[1]) for ask in orderbook.get('asks', [])[:10])

            # Получаем историю цен
            price_history = get_price_history(MARKET_SYMBOL.upper(), limit=24)
            if price_history:
                market_data["price_history"] = price_history

            # Получаем недавние сделки
            recent_trades = get_recent_trades(limit=20)
            if recent_trades:
                market_data["recent_trades"] = recent_trades

            # Получаем решение от ИИ
            ai_decision = get_ai_trading_decision(qtc_balance, market_data)

            if ai_decision:
                strategy = ai_decision.get("strategy")
                parameters = ai_decision.get("parameters", {})

                # Выполняем выбранную стратегию
                if strategy == "market":
                    sell_result = create_sell_order_safetrade(qtc_balance, "market")
                    bot.send_message(ADMIN_CHAT_ID,
                                     f"🔄 *Автоматическая продажа (Market, рекомендация ИИ)*\n\n{sell_result}",
                                     parse_mode='Markdown')

                elif strategy == "limit":
                    price = parameters.get("price", 0)
                    if price > 0:
                        sell_result = create_sell_order_safetrade(qtc_balance, "limit", price)
                        bot.send_message(ADMIN_CHAT_ID,
                                         f"🔄 *Автоматическая продажа (Limit, рекомендация ИИ)*\n\n{sell_result}",
                                         parse_mode='Markdown')
                    else:
                        # Если цена не указана, используем рыночный ордер
                        sell_result = create_sell_order_safetrade(qtc_balance, "market")
                        bot.send_message(ADMIN_CHAT_ID,
                                         f"🔄 *Автоматическая продажа (Market, fallback из-за отсутствия цены)*\n\n{sell_result}",
                                         parse_mode='Markdown')

                elif strategy == "twap":
                    duration = parameters.get("duration_minutes", 60)
                    chunks = parameters.get("chunks", 6)
                    sold_amount, total_received = execute_twap_sell(qtc_balance, duration, chunks)
                    avg_price = total_received / sold_amount if sold_amount > 0 else 0
                    message = (
                        f"🔄 *Автоматическая продажа (TWAP, рекомендация ИИ)*\n\n"
                        f"*Продано:* `{sold_amount:.8f} QTC`\n"
                        f"*Получено:* `{total_received:.8f} USDT`\n"
                        f"*Средняя цена:* `{avg_price:.8f} USDT`\n"
                        f"*Длительность:* `{duration} минут`\n"
                        f"*Количество частей:* `{chunks}`"
                    )
                    bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')

                elif strategy == "iceberg":
                    visible_amount = parameters.get("visible_amount", 0.1)
                    max_attempts = parameters.get("max_attempts", 20)
                    sold_amount, total_received = execute_iceberg_sell(qtc_balance, visible_amount, max_attempts)
                    avg_price = total_received / sold_amount if sold_amount > 0 else 0
                    message = (
                        f"🔄 *Автоматическая продажа (Iceberg, рекомендация ИИ)*\n\n"
                        f"*Продано:* `{sold_amount:.8f} QTC`\n"
                        f"*Получено:* `{total_received:.8f} USDT`\n"
                        f"*Средняя цена:* `{avg_price:.8f} USDT`\n"
                        f"*Видимая часть:* `{visible_amount} QTC`\n"
                        f"*Максимум попыток:* `{max_attempts}`"
                    )
                    bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')

                else:
                    # Неизвестная стратегия, используем рыночный ордер
                    sell_result = create_sell_order_safetrade(qtc_balance, "market")
                    bot.send_message(ADMIN_CHAT_ID,
                                     f"🔄 *Автоматическая продажа (Market, неизвестная стратегия ИИ)*\n\n{sell_result}",
                                     parse_mode='Markdown')

            else:
                # Если ИИ недоступен или не смог принять решение, используем адаптивную стратегию
                sold_amount, total_received = execute_adaptive_sell(qtc_balance)
                if sold_amount and total_received:
                    avg_price = total_received / sold_amount
                    message = (
                        f"🔄 *Автоматическая продажа (Adaptive, без ИИ)*\n\n"
                        f"*Продано:* `{sold_amount:.8f} QTC`\n"
                        f"*Получено:* `{total_received:.8f} USDT`\n"
                        f"*Средняя цена:* `{avg_price:.8f} USDT`"
                    )
                    bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                else:
                    # Если адаптивная стратегия не сработала, используем простой рыночный ордер
                    sell_result = create_sell_order_safetrade(qtc_balance, "market")
                    bot.send_message(ADMIN_CHAT_ID, f"🔄 *Автоматическая продажа (Market, fallback)*\n\n{sell_result}",
                                     parse_mode='Markdown')

        except Exception as e:
            error_message = f"❌ Ошибка при автоматической продаже: {e}"
            print(error_message)
            bot.send_message(ADMIN_CHAT_ID, error_message, parse_mode='Markdown')

        # Ждем до следующей проверки
        time.sleep(3600)


# --- Обработчики команд Telegram ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Обработчик команды /start с подробным описанием."""
    welcome_text = """
👋 *Добро пожаловать в бот для управления биржей SafeTrade с поддержкой ИИ!*
Этот бот позволяет вам взаимодействовать с вашим аккаунтом на бирже SafeTrade прямо из Telegram.
Искусственный интеллект анализирует рыночные условия и выбирает оптимальную стратегию для продажи QTC.
*Доступные команды:*
✅ `/start` - Показать это приветственное сообщение и список команд.
💰 `/balance` - Показать все ваши ненулевые балансы на спотовом кошельке.
📉 `/sell_qtc` - Создать рыночный ордер на продажу *всего доступного* баланса QTC за USDT.
📊 `/history` - Показать историю ваших ордеров.
🤖 `/ai_status` - Показать статус ИИ и последние решения.
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
    balance_info = get_balances_safetrade()
    bot.send_message(message.chat.id, balance_info, parse_mode='Markdown')


@bot.message_handler(commands=['sell_qtc'])
def handle_sell(message):
    """Обработчик команды /sell_qtc."""
    bot.send_message(message.chat.id, f"Ищу `{CURRENCY_TO_SELL}` на балансе для продажи...", parse_mode='Markdown')
    try:
        headers = get_auth_headers()
        response = scraper.get(BASE_URL + "/trade/account/balances/spot", headers=headers)
        response.raise_for_status()
        balances = response.json()
        qtc_balance = 0.0
        if isinstance(balances, list):
            for balance in balances:
                if balance.get("currency", "").upper() == CURRENCY_TO_SELL:
                    qtc_balance = float(balance.get("balance", 0))
                    break
        if qtc_balance > 0:
            bot.send_message(message.chat.id,
                             f"✅ Обнаружено `{qtc_balance}` {CURRENCY_TO_SELL}. Создаю ордер на продажу...",
                             parse_mode='Markdown')
            sell_result = create_sell_order_safetrade(qtc_balance)
            bot.send_message(message.chat.id, sell_result, parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, f"Баланс `{CURRENCY_TO_SELL}` равен 0. Продавать нечего.",
                             parse_mode='Markdown')
    except Exception as e:
        error_message = f"❌ Произошла ошибка перед созданием ордера: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nОтвет сервера: {e.response.text}"
        bot.send_message(message.chat.id, error_message)


@bot.message_handler(commands=['history'])
def handle_history(message):
    """Обработчик команды /history с корректным отображением исполненных ордеров."""
    bot.send_message(message.chat.id, "🔍 Запрашиваю историю ордеров с SafeTrade...")
    orders = get_order_history(limit=10)
    if orders and isinstance(orders, list) and len(orders) > 0:
        history_text = "📊 *История ваших ордеров:*\n\n"
        for order in orders:
            order_id = order.get('id', 'N/A')
            created_at = order.get('created_at', 'N/A')
            try:
                dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_time = created_at
            amount_str = f"`{order.get('amount', 'N/A')}`"
            price_str = f"`{order.get('price', 'N/A')}`"
            total_str = f"`{order.get('total', 'N/A')}`"
            if order.get('state') == 'done':
                trades = get_order_trades(order_id)
                if trades and isinstance(trades, list) and len(trades) > 0:
                    total_amount = sum(float(trade.get('amount', 0)) for trade in trades)
                    total_sum = sum(float(trade.get('total', 0)) for trade in trades)
                    avg_price = total_sum / total_amount if total_amount > 0 else 0
                    amount_str = f"`{total_amount:.8f}`"
                    price_str = f"`{avg_price:.8f}` (средняя)"
                    total_str = f"`{total_sum:.8f}`"
            history_text += (
                f"*ID ордера:* `{order_id}`\n"
                f"*Пара:* `{order.get('market', 'N/A').upper()}`\n"
                f"*Тип:* `{order.get('type', 'N/A').capitalize()}`\n"
                f"*Сторона:* `{order.get('side', 'N/A').capitalize()}`\n"
                f"*Объем:* {amount_str} {CURRENCY_TO_SELL}\n"
                f"*Цена:* {price_str} {CURRENCY_TO_BUY}\n"
                f"*Сумма:* {total_str} {CURRENCY_TO_BUY}\n"
                f"*Статус:* `{order.get('state', 'N/A').capitalize()}`\n"
                f"*Время создания:* `{formatted_time}`\n\n"
            )
        bot.send_message(message.chat.id, history_text, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "История ордеров пуста.")


@bot.message_handler(commands=['ai_status'])
def handle_ai_status(message):
    """Обработчик команды /ai_status."""
    if not cerebras_client:
        bot.send_message(message.chat.id, "❌ ИИ недоступен. Проверьте настройки API ключа Cerebras.")
        return

    # Получаем последние решения ИИ
    recent_decisions = get_recent_ai_decisions(limit=5)

    status_text = f"🤖 *Статус ИИ-ассистента*\n\n"
    status_text += f"*Модель:* `{CEREBRAS_MODEL}`\n"
    status_text += f"*Статус:* {'✅ Активен' if cerebras_client else '❌ Неактивен'}\n\n"

    if recent_decisions:
        status_text += "*Последние решения:*\n\n"
        for decision in recent_decisions:
            timestamp = decision.get('timestamp', 'N/A')
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                formatted_time = timestamp

            decision_type = decision.get('decision_type', 'N/A')
            decision_data = decision.get('decision_data', {})
            reasoning = decision.get('reasoning', 'N/A')

            strategy = decision_data.get('strategy', 'N/A')
            parameters = decision_data.get('parameters', {})

            status_text += f"*Время:* `{formatted_time}`\n"
            status_text += f"*Тип решения:* `{decision_type}`\n"
            status_text += f"*Стратегия:* `{strategy}`\n"

            if parameters:
                params_str = ", ".join([f"{k}: `{v}`" for k, v in parameters.items()])
                status_text += f"*Параметры:* {params_str}\n"

            if reasoning and reasoning != 'N/A':
                # Ограничиваем длину обоснования
                short_reasoning = reasoning[:200] + "..." if len(reasoning) > 200 else reasoning
                status_text += f"*Обоснование:* {short_reasoning}\n"

            status_text += "\n"
    else:
        status_text += "Пока нет решений от ИИ.\n"

    bot.send_message(message.chat.id, status_text, parse_mode='Markdown')


@bot.message_handler(commands=['donate'])
def handle_donate(message):
    """Обработчик команды /donate."""
    donate_markup = types.InlineKeyboardMarkup()
    donate_button = types.InlineKeyboardButton(text="Поддержать автора ❤️", url=DONATE_URL)
    donate_markup.add(donate_button)
    bot.send_message(
        message.chat.id,
        "Если вы хотите поддержать разработку этого бота, вы можете сделать пожертвование. Спасибо!",
        reply_markup=donate_markup
    )


# --- Основной цикл бота ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print(
            "[CRITICAL] Не все переменные окружения установлены! Проверьте SAFETRADE_API_KEY, SAFETRADE_API_SECRET, TELEGRAM_BOT_TOKEN и ADMIN_CHAT_ID в файле .env")
    else:
        print("Бот SafeTrade с поддержкой ИИ запущен...")
        # Синхронизация отсутствующих записей при старте
        if supabase:
            print("🔄 Запускаю синхронизацию записей о продажах...")
            sync_missing_sales()

        # Запускаем поток для автоматической продажи QTC каждый час с использованием ИИ
        auto_sell_thread = threading.Thread(target=auto_sell_qtc_advanced, daemon=True)
        auto_sell_thread.start()
        print("🔄 Запущен автоматический режим продажи QTC каждый час с использованием ИИ")

        try:
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ai_status = "с поддержкой ИИ" if cerebras_client else "без поддержки ИИ"
            bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *Бот SafeTrade успешно запущен!*\n\n*Время запуска:* `{start_time}`\n*Режим:* {ai_status}\nОжидаю команды...\n\n🔄 *Автоматическая продажа QTC каждый час включена*",
                parse_mode='Markdown'
            )
            print(f"Уведомление о запуске отправлено администратору (Chat ID: {ADMIN_CHAT_ID})")
        except Exception as e:
            print(f"[WARNING] Не удалось отправить уведомление о запуске администратору. Ошибка: {e}")

        bot.infinity_polling()