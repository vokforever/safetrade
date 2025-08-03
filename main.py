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

# --- НАСТРОЙКИ ---
load_dotenv()

# Загружаем токены и ID из переменных окружения
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # ID администратора для уведомлений

# Убедимся, что секрет в байтовом представлении для hmac
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None

BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"

# --- ИНИЦИАЛИЗАЦИЯ ---

# Создаем экземпляр скрейпера для обхода защиты Cloudflare
scraper = cloudscraper.create_scraper()

# Инициализация бота Telegram
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_qtc')


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
    method = "GET"
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


def create_sell_order_safetrade(amount):
    """Создает ордер на продажу и возвращает отформатированный результат."""
    method = "POST"
    path = "/trade/market/orders"
    url = BASE_URL + path

    payload = {
        "market": MARKET_SYMBOL,
        "side": "sell",
        "ord_type": "market",
        "volume": str(amount)
    }

    try:
        headers = get_auth_headers()
        response = scraper.post(url, headers=headers, json=payload)
        response.raise_for_status()
        order_details = response.json()

        return (
            f"✅ *Успешно размещен ордер на продажу!*\n\n"
            f"*Биржа:* SafeTrade\n"
            f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
            f"*Тип:* `{order_details.get('ord_type', 'N/A').capitalize()}`\n"
            f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
            f"*Объем:* `{order_details.get('volume', 'N/A')} {CURRENCY_TO_SELL}`"
        )

    except Exception as e:
        error_message = f"❌ Ошибка при создании ордера на продажу на SafeTrade: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nОтвет сервера: `{e.response.text}`"
        return error_message


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

📉 `/sell_qtc` - Создать рыночный ордер на продажу *всего доступного* баланса QTC за USDT.

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


# --- Основной цикл бота ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print(
            "[CRITICAL] Не все переменные окружения установлены! Проверьте SAFETRADE_API_KEY, SAFETRADE_API_SECRET, TELEGRAM_BOT_TOKEN и ADMIN_CHAT_ID в файле .env")
    else:
        print("Бот SafeTrade запущен...")
        try:
            # Отправка уведомления о запуске администратору
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *Бот SafeTrade успешно запущен!*\n\n*Время запуска:* `{start_time}`\nОжидаю команды...",
                parse_mode='Markdown'
            )
            print(f"Уведомление о запуске отправлено администратору (Chat ID: {ADMIN_CHAT_ID})")
        except Exception as e:
            print(f"[WARNING] Не удалось отправить уведомление о запуске администратору. Ошибка: {e}")

        # Запуск бесконечного опроса Telegram API
        bot.infinity_polling()