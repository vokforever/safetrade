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

# --- НАСТРОЙКИ ---
load_dotenv()
# Загружаем токены и ID из переменных окружения
API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # ID администратора для уведомлений

# URL для пожертвований
DONATE_URL = "https://boosty.to/vokforever/donate"

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

# Настраиваем клавиатуру с командами
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_qtc')
menu_markup.row('/history', '/donate')


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


def create_sell_order_safetrade(amount):
    """Создает ордер на продажу и возвращает отформатированный результат."""
    path = "/trade/market/orders"
    url = BASE_URL + path
    payload = {
        "market": MARKET_SYMBOL,
        "side": "sell",
        "type": "market",
        "amount": str(amount)
    }
    try:
        headers = get_auth_headers()
        response = scraper.post(url, headers=headers, json=payload)
        response.raise_for_status()
        order_details = response.json()

        order_id = order_details.get('id')
        order_amount = order_details.get('amount', amount)

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
    path = "/trade/market/trades"  # ИСПРАВЛЕНО: Правильный эндпоинт
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        # ИСПРАВЛЕНО: Добавляем фильтрацию по ID ордера
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
            return
    print(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток")


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
📊 `/history` - Показать историю ваших ордеров.
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
        print("Бот SafeTrade запущен...")
        try:
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *Бот SafeTrade успешно запущен!*\n\n*Время запуска:* `{start_time}`\nОжидаю команды...",
                parse_mode='Markdown'
            )
            print(f"Уведомление о запуске отправлено администратору (Chat ID: {ADMIN_CHAT_ID})")
        except Exception as e:
            print(f"[WARNING] Не удалось отправить уведомление о запуске администратору. Ошибка: {e}")
        bot.infinity_polling()