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

# --- НАСТРОЙКИ ---
load_dotenv()
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DONATE_URL = "https://boosty.to/vokforever/donate"

BASE_URL = "https://api.safe.trade"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
MIN_SELL_AMOUNT = 0.00000001
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None


# --- ИНИЦИАЛИЗАЦИЯ ---
def create_safetrade_scraper():
    session = requests.Session()
    session.headers.update({
        'Accept': 'application/json',
        'User-Agent': 'SafeTrade-Client/1.0'
    })
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
        return

    lines = text.split('\n')
    current_message_parts = []
    current_length = 0
    for line in lines:
        if current_length + len(line) + 1 > MAX_MESSAGE_LENGTH:
            if current_message_parts:
                try: bot.send_message(chat_id, "\n".join(current_message_parts), **kwargs)
                except Exception as e: print(f"Ошибка при отправке части сообщения: {e}")
                current_message_parts = []
                current_length = 0
            
            if len(line) > MAX_MESSAGE_LENGTH:
                for i in range(0, len(line), MAX_MESSAGE_LENGTH):
                    chunk = line[i:i + MAX_MESSAGE_LENGTH]
                    try: bot.send_message(chat_id, chunk, **kwargs)
                    except Exception as e: print(f"Ошибка при отправке принудительно разбитого куска: {e}")
            else:
                current_message_parts.append(line)
                current_length += len(line) + 1
        else:
            current_message_parts.append(line)
            current_length += len(line) + 1
    if current_message_parts:
        try: bot.send_message(chat_id, "\n".join(current_message_parts), **kwargs)
        except Exception as e: print(f"Ошибка при отправке последней части сообщения: {e}")


# --- Функции API SafeTrade ---

def generate_signature(nonce, path, body, secret_bytes):
    string_to_sign = nonce + path + body
    return hmac.new(secret_bytes, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

def get_auth_headers(path, body=''):
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
    path = "/api/v2/peatio/account/balances"
    url = BASE_URL + path
    
    try:
        headers = get_auth_headers(path, '')
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
    path = f"/api/v2/peatio/public/markets/{market_symbol}/tickers"
    url = BASE_URL + path
    
    try:
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        ticker_data = response.json()
        
        if isinstance(ticker_data, dict) and 'ticker' in ticker_data:
            return float(ticker_data['ticker'].get('buy', 0))
        return None
    except Exception as e:
        print(f"Ошибка при получении цены: {e}")
        return None

def create_sell_order_safetrade(amount):
    path = "/api/v2/peatio/market/orders"
    url = BASE_URL + path
    
    current_bid_price = get_current_bid_price(MARKET_SYMBOL)
    if current_bid_price is None or current_bid_price <= 0:
        return f"❌ Не удалось получить актуальную цену для создания ордера."
    
    payload = {
        "market": MARKET_SYMBOL,
        "side": "sell", 
        "volume": str(amount),
        "ord_type": "limit",
        "price": str(current_bid_price)
    }
    
    body = json.dumps(payload)
    
    try:
        headers = get_auth_headers(path, body)
        response = scraper.post(url, headers=headers, data=body, timeout=30)
        response.raise_for_status()
        order_details = response.json()
        
        if 'id' in order_details:
            return format_order_success(order_details)
        else:
            return f"❌ Неожиданный ответ при создании ордера: {order_details}"
    except Exception as e:
        error_text = f"❌ Ошибка при создании ордера: {e}"
        if hasattr(e, 'response') and e.response is not None:
             error_text += f"\nОтвет сервера: ```{e.response.text}```"
        return error_text

def format_order_success(order_details):
    return (
        f"✅ *Успешно размещен ордер на продажу!*\n\n"
        f"*ID ордера:* `{order_details.get('id', 'N/A')}`\n"
        f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
        f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
        f"*Объем:* `{order_details.get('volume', 'N/A')} {CURRENCY_TO_SELL}`\n"
        f"*Цена:* `{order_details.get('price', 'N/A')} {CURRENCY_TO_BUY}`\n"
        f"*Статус:* `{order_details.get('state', 'N/A').capitalize()}`"
    )

# --- Обработчики команд ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    welcome_text = """
    👋 *Добро пожаловать в бот для управления биржей SafeTrade!*
    *Доступные команды:*
    ✅ `/start` - Показать это приветственное сообщение.
    💰 `/balance` - Показать ненулевые балансы.
    📉 `/sell_qtc` - Продать весь доступный баланс QTC за USDT.
    📊 `/history` - Показать историю последних исполненных ордеров.
    ❤️ `/donate` - Поддержать автора.
    """
    send_long_message(message.chat.id, text=welcome_text, parse_mode='Markdown', reply_markup=menu_markup)

@bot.message_handler(commands=['balance'])
def handle_balance(message):
    bot.send_message(message.chat.id, "🔍 Запрашиваю балансы с SafeTrade...")
    balance_info = get_balances_safetrade()
    send_long_message(message.chat.id, balance_info, parse_mode='Markdown')

# ... Здесь должны быть остальные ваши обработчики ...


# --- Основной цикл бота ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print("[CRITICAL] Не все переменные окружения установлены!")
        sys.exit(1)
        
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
        
        current_pid = os.getpid()
        script_name = os.path.basename(__file__)
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid and proc.info['cmdline'] and \
                   len(proc.info['cmdline']) > 1 and \
                   'python' in proc.info['cmdline'][0] and script_name in proc.info['cmdline'][1]:
                    print(f"ОШИБКА: Обнаружен другой работающий экземпляр (PID: {proc.info['pid']}). Запуск отменен.")
                    sys.exit(1)
            except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError):
                continue
        
        print("Бот SafeTrade запускается...")
        
        try:
            print("Удаляю предыдущий вебхук...")
            bot.remove_webhook()
            time.sleep(1)
            print("Вебхук успешно удален.")
        except Exception as e:
            print(f"Не удалось удалить вебхук (это нормально): {e}")

        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        send_long_message(ADMIN_CHAT_ID, f"✅ *Бот запущен!*\n*Время:* `{start_time}`", parse_mode='Markdown')
        
        # print("Планирую первую автоматическую продажу...")
        # threading.Timer(10, auto_sell_qtc).start()
        
        print("Бот начинает опрос Telegram API...")
        # =========================================================
        # ИСПРАВЛЕННАЯ СТРОКА: Убран лишний аргумент non_stop
        # =========================================================
        bot.infinity_polling(timeout=20, long_polling_timeout=30)
        
    except ValueError:
        print("[CRITICAL] ADMIN_CHAT_ID должен быть числом!")
    except Exception as e:
        print(f"[ERROR] Критическая ошибка при запуске бота: {e}")
    finally:
        print("Завершение работы бота...")
        if 'bot' in locals() and bot is not None:
            bot.stop_polling()
