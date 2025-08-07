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

# ПРАВИЛЬНЫЙ БАЗОВЫЙ URL из официального примера
BASE_URL = "https://safe.trade/api/v2"

CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"  # qtcusdt
MIN_SELL_AMOUNT = 0.00000001

# --- ИНИЦИАЛИЗАЦИЯ ---
def create_enhanced_scraper():
    """Создает скрейпер"""
    session = requests.Session()
    session.headers.update({
        'Content-Type': 'application/json;charset=utf-8',
        'Accept': 'application/json',
        'User-Agent': 'SafeTrade-Client/1.0',
        'Origin': 'https://safe.trade',
        'Referer': 'https://safe.trade/'
    })
    
    return cloudscraper.create_scraper(
        sess=session,
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
        delay=10
    )

scraper = create_enhanced_scraper()
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# --- Функции API SafeTrade (соответствуют официальному примеру) ---
def generate_signature(nonce, secret, key):
    """Генерирует подпись согласно официальному примеру"""
    hash_obj = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    # Конкатенируем nonce и key, затем вычисляем HMAC hash
    hash_obj.update((nonce + key).encode())
    signature = hash_obj.digest()
    # Конвертируем бинарную подпись в шестнадцатеричное представление
    signature_hex = binascii.hexlify(signature).decode()
    return signature_hex

def get_auth_headers():
    """Собирает заголовки для аутентификации согласно официальному примеру"""
    nonce = str(int(time.time() * 1000))  # Nonce в миллисекундах
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
    """Получает балансы согласно официальному примеру"""
    url = f"{BASE_URL}/trade/account/balances"
    
    try:
        headers = get_auth_headers()
        response = scraper.get(url, headers=headers, timeout=30)
        
        print(f"📡 Ответ от балансов: статус {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Успешный ответ: {data}")
            
            if isinstance(data, list):
                non_zero_balances = [f"{b.get('currency', '').upper()}: `{b.get('balance', '0')}`" 
                                   for b in data if float(b.get('balance', 0)) > 0]
                
                if non_zero_balances:
                    return "Ваши ненулевые балансы на SafeTrade:\n\n" + "\n".join(non_zero_balances)
                else:
                    return "У вас нет ненулевых балансов на SafeTrade."
            else:
                return f"Ошибка: получен неожиданный формат данных: {data}"
        else:
            return f"❌ Ошибка API: статус {response.status_code} - {response.text}"
                
    except Exception as e:
        return f"❌ Ошибка при получении балансов: {e}"

def get_current_bid_price(market_symbol):
    """Получает текущую цену покупки"""
    url = f"{BASE_URL}/trade/public/tickers/{market_symbol}"
    
    try:
        response = scraper.get(url, timeout=30)
        
        if response.status_code == 200:
            ticker_data = response.json()
            print(f"✅ Получены данные тикера: {ticker_data}")
            
            if isinstance(ticker_data, dict) and 'bid' in ticker_data:
                return float(ticker_data['bid'])
            elif isinstance(ticker_data, dict) and 'buy' in ticker_data:
                return float(ticker_data['buy'])
                
        return None
    except Exception as e:
        print(f"❌ Ошибка при получении цены: {e}")
        return None

def create_sell_order_safetrade(amount):
    """Создает ордер на продажу согласно официальному примеру"""
    url = f"{BASE_URL}/trade/market/orders"
    
    current_bid_price = get_current_bid_price(MARKET_SYMBOL)
    if current_bid_price is None or current_bid_price <= 0:
        return f"❌ Не удалось получить актуальную цену для {MARKET_SYMBOL}"
    
    # Формируем данные согласно официальному примеру
    data = {
        "market": MARKET_SYMBOL,
        "side": "sell",
        "amount": str(amount),
        "type": "limit"
    }
    data["price"] = str(current_bid_price)
    
    try:
        headers = get_auth_headers()
        print(f"🔄 Создаю ордер: {data}")
        
        response = scraper.post(url, headers=headers, json=data, timeout=30)
        
        print(f"📡 Ответ от создания ордера: статус {response.status_code}")
        
        if response.status_code == 200:
            order_details = response.json()
            print(f"✅ Ордер успешно создан: {order_details}")
            
            if 'id' in order_details:
                threading.Thread(target=track_order, args=(order_details['id'],)).start()
                return format_order_success(order_details)
            else:
                return f"❌ Неожиданный ответ: {order_details}"
        else:
            return f"❌ Ошибка создания ордера: статус {response.status_code} - {response.text}"
                
    except Exception as e:
        return f"❌ Ошибка при создании ордера: {e}"

def format_order_success(order_details):
    """Форматирует успешный ответ о создании ордера"""
    return (
        f"✅ *Успешно размещен ордер на продажу!*\n\n"
        f"*Биржа:* SafeTrade\n"
        f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
        f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
        f"*Объем:* `{order_details.get('amount', 'N/A')} {CURRENCY_TO_SELL}`\n"
        f"*Цена:* `{order_details.get('price', 'N/A')} {CURRENCY_TO_BUY}`\n"
        f"*ID ордера:* `{order_details.get('id', 'N/A')}`"
    )

def track_order(order_id):
    """Отслеживает статус ордера"""
    max_attempts = 30
    check_interval = 10
    print(f"Начинаю отслеживание ордера {order_id}...")
    
    for attempt in range(max_attempts):
        time.sleep(check_interval)
        
        url = f"{BASE_URL}/trade/market/orders/{order_id}"
        try:
            headers = get_auth_headers()
            response = scraper.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                order_info = response.json()
                order_state = order_info.get('state')
                print(f"Попытка {attempt+1}/{max_attempts}: Ордер {order_id} в состоянии: '{order_state}'")
                
                if order_state == 'done':
                    message = f"✅ *Ордер исполнен!*\n\n*ID ордера:* `{order_id}`"
                    send_long_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                    return
                elif order_state == 'cancel':
                    message = f"❌ *Ордер отменен!*\n\n*ID ордера:* `{order_id}`"
                    send_long_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                    return
            else:
                print(f"Ошибка получения статуса ордера: {response.status_code}")
                
        except Exception as e:
            print(f"Ошибка при отслеживании ордера: {e}")
    
    print(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток.")

# --- Функция очистки экземпляров бота ---
def cleanup_bot_instances():
    """Агрессивная очистка всех экземпляров бота"""
    print("🔄 Начинаю очистку экземпляров бота...")
    
    try:
        bot.remove_webhook()
        print("✅ Вебхук удален")
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Ошибка удаления вебхука: {e}")
    
    try:
        bot.set_webhook()
        print("✅ Вебхук сброшен")
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Ошибка сброса вебхука: {e}")
    
    try:
        updates = bot.get_updates()
        if updates:
            last_update_id = updates[-1].update_id
            bot.get_updates(offset=last_update_id + 1)
            print(f"✅ Очищено {len(updates)} ожидающих обновлений")
        else:
            print("✅ Нет ожидающих обновлений")
    except Exception as e:
        print(f"⚠️ Ошибка очистки обновлений: {e}")
    
    print("✅ Очистка завершена")

# --- Обработчики команд Telegram ---
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
    send_long_message(message.chat.id, text=welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['balance'])
def handle_balance(message):
    bot.send_message(message.chat.id, "🔍 Запрашиваю балансы с SafeTrade...")
    balance_info = get_balances_safetrade()
    send_long_message(message.chat.id, balance_info, parse_mode='Markdown')

# --- Основной цикл бота ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print("[CRITICAL] Не все переменные окружения установлены! Проверьте .env файл.")
    else:
        try:
            ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
            print("Бот SafeTrade запускается...")
            print(f"Используемый BASE_URL: {BASE_URL}")
            
            # Агрессивная очистка
            cleanup_bot_instances()
            
            start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                send_long_message(
                    ADMIN_CHAT_ID,
                    f"✅ *Бот SafeTrade успешно запущен!*\n\n*Время:* `{start_time}`\n*BASE_URL:* `{BASE_URL}`\nОжидаю команды...",
                    parse_mode='Markdown'
                )
                print(f"Уведомление о запуске отправлено администратору (ID: {ADMIN_CHAT_ID})")
            except Exception as e:
                print(f"Не удалось отправить уведомление: {e}")
            
            print("Бот начинает опрос Telegram API...")
            
            # Используем infinity_polling без лишних параметров
            bot.infinity_polling(timeout=20, long_polling_timeout=30)
            
        except ValueError:
            print("[CRITICAL] ADMIN_CHAT_ID в .env файле должен быть числом!")
        except Exception as e:
            print(f"[ERROR] Критическая ошибка при запуске бота: {e}")
            if ADMIN_CHAT_ID:
                try:
                    send_long_message(ADMIN_CHAT_ID, f"❌ *Критическая ошибка при запуске бота!*\n\n`{e}`", parse_mode='Markdown')
                except Exception as notify_err:
                    print(f"Не удалось отправить уведомление об ошибке администратору: {notify_err}")
        finally:
            print("Завершение работы бота. Отключаю polling...")
            try:
                bot.stop_polling()
            except:
                pass
            print("Polling остановлен. Бот выключен.")
