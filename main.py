import time
import hmac
import hashlib
import json
import os
import telebot
import threading
from telebot import types
from dotenv import load_dotenv
import cloudscraper
from datetime import datetime

# --- НАСТРОЙКИ ---
load_dotenv()

# Загружаем токены и ID из переменных окружения
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# URL для пожертвований
DONATE_URL = "https://boosty.to/vokforever/donate"

# Проверка на None, чтобы избежать ошибки, если API_SECRET отсутствует
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None
BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"  # qtcudt

# Минимальный объем QTC для продажи.
MIN_SELL_AMOUNT = 0.00000001

# --- ИНИЦИАЛИЗАЦИЯ ---

# Создаем экземпляр скрейпера для обхода защиты Cloudflare
# Добавляем более реалистичный User-Agent, чтобы имитировать обычный браузер
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# Инициализация бота Telegram. Добавляем parse_mode по умолчанию для удобства.
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode='Markdown')

# Настраиваем клавиатуру с командами
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_qtc')
menu_markup.row('/history', '/donate')

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: для отправки длинных сообщений в Telegram ---
def send_long_message(chat_id, text, **kwargs):
    """
    Разбивает длинное сообщение на части и отправляет их.
    Лимит сообщения Telegram составляет 4096 символов.
    """
    if not text:
        return

    MAX_MESSAGE_LENGTH = 4000
    if len(text) <= MAX_MESSAGE_LENGTH:
        try:
            bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            print(f"Ошибка при отправке короткого сообщения: {e}")
        return

    lines = text.split('\n')
    current_message_parts = []
    current_length = 0

    for line in lines:
        if current_length + len(line) + 1 > MAX_MESSAGE_LENGTH:
            if current_message_parts:
                try:
                    bot.send_message(chat_id, "\n".join(current_message_parts), **kwargs)
                except Exception as e:
                    print(f"Ошибка при отправке части сообщения: {e}")
                current_message_parts = []
                current_length = 0
            
            if len(line) > MAX_MESSAGE_LENGTH:
                for i in range(0, len(line), MAX_MESSAGE_LENGTH):
                    chunk = line[i:i + MAX_MESSAGE_LENGTH]
                    try:
                        bot.send_message(chat_id, chunk, **kwargs)
                    except Exception as e:
                        print(f"Ошибка при отправке принудительно разбитого куска: {e}")
            else:
                current_message_parts.append(line)
                current_length += len(line) + 1
        else:
            current_message_parts.append(line)
            current_length += len(line) + 1

    if current_message_parts:
        try:
            bot.send_message(chat_id, "\n".join(current_message_parts), **kwargs)
        except Exception as e:
            print(f"Ошибка при отправке последней части сообщения: {e}")

# --- Функции API SafeTrade ---
def generate_signature(nonce, key, secret_bytes):
    """Генерирует подпись HMAC-SHA256."""
    string_to_sign = nonce + key
    return hmac.new(secret_bytes, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

def get_auth_headers():
    """Собирает все заголовки для аутентификации."""
    nonce = str(int(time.time() * 1000))
    if not API_KEY or not API_SECRET_BYTES:
        raise ValueError("API Key или API Secret не установлены. Невозможно сгенерировать заголовки аутентификации.")
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
        response = scraper.get(url, headers=headers, timeout=30) # Добавлен таймаут
        response.raise_for_status()
        balances = response.json()
        if isinstance(balances, list):
            non_zero_balances_lines = [f"{b.get('currency', '').upper()}: `{b.get('balance', '0')}`" for b in balances if float(b.get('balance', 0)) > 0]
            if non_zero_balances_lines:
                return "Ваши ненулевые балансы на SafeTrade:\n\n" + "\n".join(non_zero_balances_lines)
            else:
                return "У вас нет ненулевых балансов на SafeTrade."
        else:
            return f"Ошибка: получен неожиданный формат данных от SafeTrade: {balances}"
    except Exception as e:
        error_message = f"❌ Ошибка при получении балансов с SafeTrade: {e}"
        if hasattr(e, 'response') and e.response is not None:
            response_text_truncated = e.response.text[:1000] + ("..." if len(e.response.text) > 1000 else "")
            error_message += f"\nОтвет сервера: `{response_text_truncated}`"
        print(error_message) # Выводим ошибку в консоль для диагностики
        return error_message

def get_current_bid_price(market_symbol):
    """Получает текущую лучшую цену покупки (бид)."""
    path = f"/trade/public/tickers/{market_symbol}"
    url = BASE_URL + path
    try:
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        ticker_data = response.json()
        if isinstance(ticker_data, dict) and 'bid' in ticker_data:
            return float(ticker_data['bid'])
        else:
            print(f"Неожиданный формат данных тикера для {market_symbol} от SafeTrade: {ticker_data}")
            return None
    except Exception as e:
        print(f"Ошибка при получении текущей цены бида для {market_symbol}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Ответ сервера (get_current_bid_price): {e.response.text}")
        return None

# Остальные функции (create_sell_order_safetrade, get_order_info и т.д.) остаются такими же, как в вашем коде.
# Я их скрыл для краткости, но они должны присутствовать в вашем финальном файле.
# ... (вставьте сюда ваши функции create_sell_order_safetrade, get_order_info, get_order_trades, get_order_history, track_order, auto_sell_qtc) ...

# --- Обработчики команд Telegram ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Обработчик команды /start с подробным описанием."""
    welcome_text = """
👋 *Добро пожаловать в бот для управления биржей SafeTrade!*
Этот бот позволяет вам взаимодействовать с вашим аккаунтом на бирже SafeTrade прямо из Telegram.
*Доступные команды:*
✅ `/start` - Показать это приветственное сообщение и список команд.
💰 `/balance` - Показать все ваши ненулевые балансы на спотовом кошельке.
📉 `/sell_qtc` - Создать *лимитный* ордер на продажу *всего доступного* баланса QTC за USDT по текущей рыночной цене (бид).
📊 `/history` - Показать историю ваших последних исполненных ордеров.
❤️ `/donate` - Поддержать автора бота.
Используйте кнопки внизу для быстрого доступа к командам.
"""
    send_long_message(message.chat.id, text=welcome_text, reply_markup=menu_markup)


@bot.message_handler(commands=['balance'])
def handle_balance(message):
    """Обработчик команды /balance."""
    bot.send_message(message.chat.id, "🔍 Запрашиваю балансы с SafeTrade...")
    balance_info = get_balances_safetrade()
    send_long_message(message.chat.id, balance_info)


@bot.message_handler(commands=['sell_qtc'])
def handle_sell(message):
    """Обработчик команды /sell_qtc."""
    bot.send_message(message.chat.id, f"Ищу `{CURRENCY_TO_SELL}` на балансе для продажи...")
    try:
        headers = get_auth_headers()
        response = scraper.get(url=BASE_URL + "/trade/account/balances/spot", headers=headers, timeout=30)
        response.raise_for_status()
        balances = response.json()
        qtc_balance = 0.0
        if isinstance(balances, list):
            for balance in balances:
                if balance.get("currency", "").upper() == CURRENCY_TO_SELL:
                    qtc_balance = float(balance.get("balance", 0))
                    break
        
        if qtc_balance > MIN_SELL_AMOUNT:
            send_long_message(message.chat.id, f"✅ Обнаружено `{qtc_balance}` {CURRENCY_TO_SELL}. Создаю лимитный ордер на продажу по рыночной цене...")
            sell_result = create_sell_order_safetrade(qtc_balance)
            send_long_message(message.chat.id, sell_result)
        else:
            send_long_message(message.chat.id, f"Баланс `{CURRENCY_TO_SELL}` равен `{qtc_balance}`. Продавать нечего или объем слишком мал (мин. `{MIN_SELL_AMOUNT}`).")
    except Exception as e:
        error_message = f"❌ Произошла ошибка перед созданием ордера: {e}"
        if hasattr(e, 'response') and e.response is not None:
            response_text_truncated = e.response.text[:1000] + ("..." if len(e.response.text) > 1000 else "")
            error_message += f"\nОтвет сервера: `{response_text_truncated}`"
        send_long_message(message.chat.id, error_message)


# ... (вставьте сюда ваши обработчики /history и /donate) ...


# --- Основной цикл бота ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print("[CRITICAL] Не все переменные окружения установлены! Проверьте SAFETRADE_API_KEY, SAFETRADE_API_SECRET, TELEGRAM_BOT_TOKEN и ADMIN_CHAT_ID.")
    else:
        try:
            ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
            print("Бот SafeTrade запущен...")
            
            # РЕШЕНИЕ ПРОБЛЕМЫ 409 Conflict: Удаляем старый вебхук перед запуском polling.
            # Это гарантирует, что предыдущие сессии не будут мешать.
            try:
                print("Удаляю предыдущий вебхук, чтобы избежать конфликтов...")
                bot.delete_webhook()
                time.sleep(1) # Небольшая пауза
                print("Вебхук успешно удален.")
            except Exception as e:
                print(f"Не удалось удалить вебхук. Ошибка: {e}. Продолжаю запуск...")
            
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            send_long_message(
                ADMIN_CHAT_ID,
                f"✅ *Бот SafeTrade успешно запущен!*\n\n*Время запуска:* `{start_time}`\nОжидаю команды...",
            )
            print(f"Уведомление о запуске отправлено администратору (Chat ID: {ADMIN_CHAT_ID})")
            
            # Запускаем автоматическую продажу
            print("Планирую первую автоматическую продажу QTC через 30 секунд...")
            threading.Timer(30, auto_sell_qtc).start()

            print("Бот начинает опрос Telegram API...")
            # Используем infinity_polling с параметром для лучшей обработки ошибок
            bot.infinity_polling(timeout=20, long_polling_timeout=30)

        except ValueError:
            print("[CRITICAL] ADMIN_CHAT_ID в .env файле должен быть числом!")
        except Exception as e:
            print(f"[ERROR] Критическая ошибка при запуске бота: {e}")
            # В случае любой другой ошибки при запуске, отправляем уведомление
            if ADMIN_CHAT_ID:
                try:
                    send_long_message(ADMIN_CHAT_ID, f"❌ *Критическая ошибка при запуске бота!*\n\n`{e}`")
                except Exception as notify_err:
                    print(f"Не удалось отправить уведомление об ошибке администратору: {notify_err}")
