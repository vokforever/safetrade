import time
import hmac
import hashlib
import json
import os
import sys
import telebot
import threading
import requests
import psutil
from telebot import types
from dotenv import load_dotenv
import cloudscraper
from datetime import datetime

# --- НАСТРОЙКИ (обновленные) ---
load_dotenv()
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DONATE_URL = "https://boosty.to/vokforever/donate"

# Правильный базовый URL и другие константы из примера
BASE_URL = "https://api.safe.trade"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
# API ожидает символ в нижнем регистре, без разделителей
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
MIN_SELL_AMOUNT = 0.00000001
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None


# --- ИНИЦИАЛИЗАЦИЯ (обновленная) ---
def create_safetrade_scraper():
    """Создает скрейпер на основе официального примера SafeTrade."""
    session = requests.Session()
    # Устанавливаем заголовки, как в официальном клиенте
    session.headers.update({
        'Accept': 'application/json',
        'User-Agent': 'SafeTrade-Client/1.0'
        # 'Content-Type' будет добавляться в get_auth_headers
    })
    
    # Cloudscraper здесь используется как запасной вариант, если биржа вдруг включит защиту,
    # но основная логика теперь в правильных заголовках.
    return cloudscraper.create_scraper(
        sess=session,
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )

scraper = create_safetrade_scraper()
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_qtc')
menu_markup.row('/history', '/donate')


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def send_long_message(chat_id, text, **kwargs):
    if not text: return
    MAX_MESSAGE_LENGTH = 4000
    if len(text) <= MAX_MESSAGE_LENGTH:
        try: bot.send_message(chat_id, text, **kwargs)
        except Exception as e: print(f"Ошибка при отправке короткого сообщения: {e}")
    # ... (здесь остальной код функции для разбивки длинных сообщений)


# --- Функции API SafeTrade (ПОЛНОСТЬЮ ИСПРАВЛЕННЫЕ) ---

def generate_signature(nonce, path, body, secret_bytes):
    """Новая, правильная функция генерации подписи согласно документации."""
    string_to_sign = nonce + path + body
    return hmac.new(secret_bytes, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

def get_auth_headers(path, body=''):
    """Новая, правильная функция сборки заголовков."""
    nonce = str(int(time.time() * 1000))
    if not API_KEY or not API_SECRET_BYTES:
        raise ValueError("API Key или API Secret не установлены.")
    
    signature = generate_signature(nonce, path, body, API_SECRET_BYTES)
    
    return {
        'X-Auth-Apikey': API_KEY,
        'X-Auth-Nonce': nonce,
        'X-Auth-Signature': signature,
        'Content-Type': 'application/json'
    }

def get_balances_safetrade():
    """Получает балансы, используя новый, правильный метод API."""
    path = "/api/v2/peatio/account/balances"
    url = BASE_URL + path
    
    try:
        # Для GET-запросов тело подписи - пустая строка
        headers = get_auth_headers(path)
        response = scraper.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        if isinstance(data, list):
            non_zero_balances = [f"{b.get('currency', '').upper()}: `{b.get('balance', '0')}`" 
                               for b in data if float(b.get('balance', 0)) > 0]
            
            if non_zero_balances:
                return "Ваши ненулевые балансы:\n\n" + "\n".join(non_zero_balances)
            else:
                return "У вас нет ненулевых балансов на SafeTrade."
        else:
            return f"Ошибка: получен неожиданный формат данных: {data}"
    except Exception as e:
        error_text = f"❌ Ошибка при получении балансов: {e}"
        if hasattr(e, 'response') and e.response is not None:
             error_text += f"\nОтвет сервера: ```{e.response.text}```"
        return error_text

def get_current_bid_price(market_symbol):
    """Получает текущую цену покупки (buy price), как в примере."""
    path = f"/api/v2/peatio/public/markets/{market_symbol}/tickers"
    url = BASE_URL + path
    
    try:
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        ticker_data = response.json()
        
        # В примере цена находится в поле 'ticker', цена покупки - 'buy'
        if isinstance(ticker_data, dict) and 'ticker' in ticker_data:
            return float(ticker_data['ticker'].get('buy', 0))
        return None
    except Exception as e:
        print(f"Ошибка при получении цены: {e}")
        return None

def create_sell_order_safetrade(amount):
    """Создает ордер на продажу, используя новый, правильный метод API."""
    path = "/api/v2/peatio/market/orders"
    url = BASE_URL + path
    
    current_bid_price = get_current_bid_price(MARKET_SYMBOL)
    if current_bid_price is None or current_bid_price <= 0:
        return f"❌ Не удалось получить актуальную цену для создания ордера."
    
    payload = {
        "market": MARKET_SYMBOL,
        "side": "sell", 
        "volume": str(amount),  # Правильное поле: 'volume'
        "ord_type": "limit",    # В примере используется 'ord_type'
        "price": str(current_bid_price)
    }
    
    # Для POST-запросов тело подписи - это JSON-строка
    body = json.dumps(payload)
    
    try:
        headers = get_auth_headers(path, body)
        # Используем data=body, а не json=payload
        response = scraper.post(url, headers=headers, data=body, timeout=30)
        response.raise_for_status()
        order_details = response.json()
        
        if 'id' in order_details:
            # threading.Thread(target=track_order, args=(order_details['id'],)).start()
            return format_order_success(order_details)
        else:
            return f"❌ Неожиданный ответ при создании ордера: {order_details}"
    except Exception as e:
        error_text = f"❌ Ошибка при создании ордера: {e}"
        if hasattr(e, 'response') and e.response is not None:
             error_text += f"\nОтвет сервера: ```{e.response.text}```"
        return error_text

def format_order_success(order_details):
    """Форматирует успешный ответ с правильными полями."""
    return (
        f"✅ *Успешно размещен ордер на продажу!*\n\n"
        f"*ID ордера:* `{order_details.get('id', 'N/A')}`\n"
        f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
        f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
        f"*Объем:* `{order_details.get('volume', 'N/A')} {CURRENCY_TO_SELL}`\n"
        f"*Цена:* `{order_details.get('price', 'N/A')} {CURRENCY_TO_BUY}`\n"
        f"*Статус:* `{order_details.get('state', 'N/A').capitalize()}`"
    )

# Остальные функции (auto_sell_qtc, обработчики команд) остаются прежними,
# так как они вызывают уже исправленные API-функции.
# ...


# --- Основной цикл бота (с защитой от дубликатов) ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print("[CRITICAL] Не все переменные окружения установлены!")
        sys.exit(1)
        
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
        
        # Проверка на дубликаты процессов
        current_pid = os.getpid()
        script_name = os.path.basename(__file__)
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid and proc.info['cmdline'] and \
                   'python' in proc.info['cmdline'][0] and script_name in proc.info['cmdline'][1]:
                    print(f"ОШИБКА: Обнаружен другой работающий экземпляр (PID: {proc.info['pid']}). Запуск отменен.")
                    sys.exit(1)
            except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError):
                continue
        
        print("Бот SafeTrade запускается...")
        
        # Гарантированная очистка старых сессий Telegram
        try:
            print("Удаляю предыдущий вебхук...")
            bot.remove_webhook()
            time.sleep(1)
            print("Вебхук успешно удален.")
        except Exception as e:
            print(f"Не удалось удалить вебхук (это нормально): {e}")

        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # send_long_message(ADMIN_CHAT_ID, f"✅ *Бот запущен!*\n*Время:* `{start_time}`", parse_mode='Markdown')
        
        # print("Планирую первую автоматическую продажу через 10 секунд...")
        # threading.Timer(10, auto_sell_qtc).start()
        
        print("Бот начинает опрос Telegram API...")
        bot.infinity_polling(non_stop=True)
        
    except ValueError:
        print("[CRITICAL] ADMIN_CHAT_ID должен быть числом!")
    except Exception as e:
        print(f"[ERROR] Критическая ошибка при запуске бота: {e}")
    finally:
        print("Завершение работы бота...")
        bot.stop_polling()
