import time
import hmac
import hashlib
import binascii
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

# ПРАВИЛЬНЫЙ БАЗОВЫЙ URL из официального примера
BASE_URL = "https://safe.trade/api/v2"

CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
MIN_SELL_AMOUNT = 0.00000001


# --- ИНИЦИАЛИЗАЦИЯ ---
def create_safetrade_scraper():
    """Создает скрейпер с правильными заголовками по умолчанию."""
    session = requests.Session()
    session.headers.update({
        'Accept': 'application/json',
        'User-Agent': 'SafeTrade-Client/1.0', # Как в официальном клиенте
    })
    return cloudscraper.create_scraper(sess=session)

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
        except Exception as e: print(f"Ошибка при отправке сообщения: {e}")
        return
    parts = [text[i:i+MAX_MESSAGE_LENGTH] for i in range(0, len(text), MAX_MESSAGE_LENGTH)]
    for part in parts:
        try:
            bot.send_message(chat_id, part, **kwargs)
            time.sleep(0.1)
        except Exception as e: print(f"Ошибка при отправке части сообщения: {e}")


# --- Функции API SafeTrade (соответствуют официальному примеру) ---

def generate_signature(nonce, secret, key):
    """Генерирует подпись согласно официальному примеру."""
    hash_obj = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    hash_obj.update((nonce + key).encode())
    signature = hash_obj.digest()
    return binascii.hexlify(signature).decode()

def get_auth_headers():
    """Собирает заголовки для аутентификации."""
    nonce = str(int(time.time() * 1000))
    if not API_KEY or not API_SECRET:
        raise ValueError("API Key или API Secret не установлены.")
    
    signature = generate_signature(nonce, API_SECRET, API_KEY)
    
    return {
        "X-Auth-Apikey": API_KEY,
        "X-Auth-Nonce": nonce,
        "X-Auth-Signature": signature,
        "Content-Type": "application/json;charset=utf-8"
    }

def get_balances_safetrade():
    """Получает балансы согласно официальному API."""
    url = f"{BASE_URL}/trade/account/balances"
    try:
        headers = get_auth_headers()
        response = scraper.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list):
            non_zero_balances = [f"{b.get('currency', '').upper()}: `{b.get('balance', '0')}`" 
                               for b in data if float(b.get('balance', 0)) > 0]
            if non_zero_balances:
                return "Ваши ненулевые балансы:\n\n" + "\n".join(non_zero_balances)
            return "У вас нет ненулевых балансов."
        return f"Ошибка: получен неожиданный формат данных: {data}"
    except Exception as e:
        error_text = f"❌ Ошибка при получении балансов: {e}"
        if hasattr(e, 'response'): error_text += f"\nОтвет сервера: ```{e.response.text}```"
        return error_text

def get_current_bid_price(market_symbol):
    """Получает текущую лучшую цену покупки."""
    url = f"{BASE_URL}/trade/public/tickers/{market_symbol}"
    try:
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        ticker_data = response.json()
        if isinstance(ticker_data, dict) and 'bid' in ticker_data:
            return float(ticker_data['bid'])
        return None
    except Exception as e:
        print(f"❌ Ошибка при получении цены: {e}")
        return None

def create_sell_order_safetrade(amount):
    """Создает ордер на продажу согласно официальному API."""
    url = f"{BASE_URL}/trade/market/orders"
    
    current_bid_price = get_current_bid_price(MARKET_SYMBOL)
    if current_bid_price is None or current_bid_price <= 0:
        return f"❌ Не удалось получить актуальную цену для {MARKET_SYMBOL}"
    
    data = {
        "market": MARKET_SYMBOL,
        "side": "sell",
        "amount": str(amount),
        "type": "limit",
        "price": str(current_bid_price)
    }
    
    try:
        headers = get_auth_headers()
        # Для POST запросов используем json=data
        response = scraper.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        order_details = response.json()
        
        if 'id' in order_details:
            return format_order_success(order_details)
        return f"❌ Неожиданный ответ от API: {order_details}"
    except Exception as e:
        error_text = f"❌ Ошибка при создании ордера: {e}"
        if hasattr(e, 'response'): error_text += f"\nОтвет сервера: ```{e.response.text}```"
        return error_text

def format_order_success(order_details):
    """Форматирует успешный ответ о создании ордера."""
    return (
        f"✅ *Успешно размещен ордер!*\n\n"
        f"*ID ордера:* `{order_details.get('id', 'N/A')}`\n"
        f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
        f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
        f"*Объем:* `{order_details.get('amount', 'N/A')} {CURRENCY_TO_SELL}`\n"
        f"*Цена:* `{order_details.get('price', 'N/A')} {CURRENCY_TO_BUY}`\n"
        f"*Статус:* `{order_details.get('state', 'N/A').capitalize()}`"
    )


# --- Обработчики команд Telegram ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    send_long_message(message.chat.id, "👋 Добро пожаловать! Используйте кнопки для управления ботом.", parse_mode='Markdown', reply_markup=menu_markup)

@bot.message_handler(commands=['balance'])
def handle_balance(message):
    bot.send_message(message.chat.id, "🔍 Запрашиваю балансы...")
    balance_info = get_balances_safetrade()
    send_long_message(message.chat.id, balance_info, parse_mode='Markdown')

@bot.message_handler(commands=['sell_qtc'])
def handle_sell_qtc(message):
    bot.send_message(message.chat.id, f"Ищу `{CURRENCY_TO_SELL}` на балансе...", parse_mode='Markdown')
    # Здесь должна быть логика получения баланса QTC и вызова create_sell_order_safetrade
    # Для примера, продаем фиксированное количество:
    result = create_sell_order_safetrade("1.0") # Замените на реальное получение баланса
    send_long_message(message.chat.id, result, parse_mode='Markdown')

# ... Другие обработчики ...


# --- Основной цикл бота ---
def cleanup_bot_instances():
    """Надежная очистка экземпляров бота перед запуском."""
    print("🔄 Начинаю очистку экземпляров бота...")
    try:
        bot.remove_webhook()
        print("✅ Вебхук удален.")
        time.sleep(1)
        updates = bot.get_updates(offset=-1, timeout=1)
        if updates:
            last_update_id = updates[-1].update_id
            bot.get_updates(offset=last_update_id + 1, timeout=1)
            print(f"✅ Очищено {len(updates)} ожидающих обновлений.")
        else:
            print("✅ Нет ожидающих обновлений.")
    except Exception as e:
        print(f"⚠️ Ошибка во время очистки (это может быть нормально): {e}")
    print("✅ Очистка завершена.")

if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print("[CRITICAL] Не все переменные окружения установлены!")
        sys.exit(1)
        
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
        
        # Проверка на дубликаты
        current_pid = os.getpid()
        script_name = os.path.basename(__file__)
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid and proc.info['cmdline'] and len(proc.info['cmdline']) > 1 and 'python' in proc.info['cmdline'][0] and script_name in proc.info['cmdline'][1]:
                    print(f"ОШИБКА: Обнаружен другой работающий экземпляр (PID: {proc.info['pid']}). Запуск отменен.")
                    sys.exit(1)
            except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError):
                continue
        
        print("Бот SafeTrade запускается...")
        
        cleanup_bot_instances()
        
        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        send_long_message(ADMIN_CHAT_ID, f"✅ *Бот успешно запущен!*\n*Время:* `{start_time}`", parse_mode='Markdown')
        
        print("Бот начинает опрос Telegram API...")
        bot.infinity_polling(timeout=20, long_polling_timeout=30)
        
    except ValueError:
        print("[CRITICAL] ADMIN_CHAT_ID должен быть числом!")
    except Exception as e:
        print(f"[ERROR] Критическая ошибка при запуске бота: {e}")
    finally:
        print("Завершение работы бота...")
        if 'bot' in locals() and bot is not None:
            bot.stop_polling()
