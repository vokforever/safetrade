import time
import hmac
import hashlib
import json
import os
import telebot
import threading
import requests # Убедитесь, что этот импорт есть
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
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"

# Минимальный объем QTC для продажи.
MIN_SELL_AMOUNT = 0.00000001

# --- ИНИЦИАЛИЗАЦИЯ ---

# Продвинутая инициализация для обхода защиты Cloudflare
# Создаем сессию вручную, чтобы передать более сложные параметры
session = requests.Session()

# Устанавливаем полный набор заголовков, типичный для современного браузера
session.headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'TE': 'trailers'
}

# Создаем скрейпер на основе нашей кастомизированной сессии
scraper = cloudscraper.create_scraper(
    sess=session,
    delay=10,  # Добавляем задержку для имитации человеческого поведения
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# Инициализация бота Telegram.
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Настраиваем клавиатуру с командами
menu_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
menu_markup.row('/balance', '/sell_qtc')
menu_markup.row('/history', '/donate')


# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: для отправки длинных сообщений ---
def send_long_message(chat_id, text, **kwargs):
    """
    Разбивает длинное сообщение на части и отправляет их.
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
        raise ValueError("API Key или API Secret не установлены.")
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
        response = scraper.get(url, headers=headers, timeout=30)
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


def create_sell_order_safetrade(amount):
    """Создает лимитный ордер на продажу по рыночной цене."""
    path = "/trade/market/orders"
    url = BASE_URL + path

    current_bid_price = get_current_bid_price(MARKET_SYMBOL)
    if current_bid_price is None or current_bid_price <= 0:
        return (f"❌ Не удалось получить актуальную цену для `{CURRENCY_TO_SELL}/{CURRENCY_TO_BUY}`. "
                f"Невозможно создать ордер.")

    price_to_sell_at = current_bid_price
    payload = {
        "market": MARKET_SYMBOL,
        "side": "sell",
        "type": "limit",
        "amount": str(amount),
        "price": str(price_to_sell_at)
    }

    try:
        headers = get_auth_headers()
        response = scraper.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        order_details = response.json()

        order_id = order_details.get('id')
        if order_id:
            threading.Thread(target=track_order, args=(order_id,)).start()

        return (
            f"✅ *Успешно размещен ордер на продажу!*\n\n"
            f"*Биржа:* SafeTrade\n"
            f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
            f"*Тип:* `{order_details.get('type', 'N/A').capitalize()}`\n"
            f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
            f"*Заявленный объем:* `{order_details.get('amount', amount)} {CURRENCY_TO_SELL}`\n"
            f"*Заданная цена:* `{order_details.get('price', price_to_sell_at)} {CURRENCY_TO_BUY}`\n"
            f"*ID ордера:* `{order_id}`"
        )
    except Exception as e:
        error_message = f"❌ Ошибка при создании ордера на продажу: {e}"
        if hasattr(e, 'response') and e.response is not None:
            response_text_truncated = e.response.text[:1000] + ("..." if len(e.response.text) > 1000 else "")
            error_message += f"\nОтвет сервера: `{response_text_truncated}`"
        return error_message


def get_order_info(order_id):
    """Получает информацию о конкретном ордере."""
    path = f"/trade/market/orders/{order_id}"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        response = scraper.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении информации об ордере {order_id}: {e}")
        return None


def get_order_trades(order_id):
    """Получает сделки по конкретному ордеру."""
    path = "/trade/market/trades"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        params = {"order_id": str(order_id)}
        response = scraper.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении сделок по ордеру {order_id}: {e}")
        return []


def get_order_history(limit=10):
    """Получает историю исполненных ордеров."""
    path = "/trade/market/orders"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        params = {"market": MARKET_SYMBOL, "limit": limit, "state": "done"}
        response = scraper.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении истории ордеров: {e}")
        return []


def track_order(order_id):
    """Отслеживает статус ордера и уведомляет о его исполнении/отмене."""
    max_attempts = 30
    check_interval = 10

    print(f"Начинаю отслеживание ордера {order_id}...")
    for attempt in range(max_attempts):
        time.sleep(check_interval)
        order_info = get_order_info(order_id)

        if not order_info:
            print(f"Попытка {attempt+1}/{max_attempts}: Не удалось получить информацию об ордере {order_id}.")
            continue

        order_state = order_info.get('state')
        print(f"Попытка {attempt+1}/{max_attempts}: Ордер {order_id} в состоянии: '{order_state}'")

        if order_state == 'done':
            trades = get_order_trades(order_id)
            total_amount = sum(float(trade.get('amount', 0)) for trade in trades)
            total_sum = sum(float(trade.get('total', 0)) for trade in trades)
            avg_price = total_sum / total_amount if total_amount > 0 else 0
            
            message = (
                f"✅ *Ордер исполнен!*\n\n"
                f"*ID ордера:* `{order_id}`\n"
                f"*Продано:* `{total_amount:.8f} {CURRENCY_TO_SELL}`\n"
                f"*Получено:* `{total_sum:.8f} {CURRENCY_TO_BUY}`\n"
                f"*Средняя цена:* `{avg_price:.8f} {CURRENCY_TO_BUY}`"
            )
            send_long_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
            return
        elif order_state == 'cancel':
            message = (f"❌ *Ордер отменен!*\n\n*ID ордера:* `{order_id}`")
            send_long_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
            return

    print(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток.")
    final_order_info = get_order_info(order_id)
    if final_order_info and final_order_info.get('state') not in ['done', 'cancel']:
        message = (
            f"⚠️ *Отслеживание ордера завершено по таймауту!*\n\n"
            f"*ID ордера:* `{order_id}`\n"
            f"*Последний известный статус:* `{final_order_info.get('state', 'N/A').capitalize()}`\n"
            f"Проверьте статус ордера вручную."
        )
        send_long_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')


def auto_sell_qtc():
    """Функция для автоматической продажи QTC."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Запущена автоматическая проверка QTC...")
    try:
        if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
            print("[CRITICAL] Не все переменные окружения установлены для авто-продажи.")
            return

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
            print(f"Обнаружен баланс {qtc_balance} {CURRENCY_TO_SELL}. Инициирую продажу.")
            sell_result = create_sell_order_safetrade(qtc_balance)
            send_long_message(ADMIN_CHAT_ID, f"🔔 *Авто-продажа QTC:*\n\n{sell_result}", parse_mode='Markdown')
        else:
            print(f"Баланс {CURRENCY_TO_SELL} ({qtc_balance}) слишком мал. Пропускаю.")
            
    except Exception as e:
        error_message = f"❌ *Ошибка при автоматической продаже QTC:* {e}"
        if hasattr(e, 'response') and e.response is not None:
            response_text_truncated = e.response.text[:1000] + "..."
            error_message += f"\nОтвет сервера: `{response_text_truncated}`"
        send_long_message(ADMIN_CHAT_ID, error_message, parse_mode='Markdown')
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error_message}")
    finally:
        # Планируем следующий запуск через 1 час (3600 секунд)
        threading.Timer(3600, auto_sell_qtc).start()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Следующая авто-продажа запланирована через 1 час.")


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
    send_long_message(message.chat.id, text=welcome_text, parse_mode='Markdown', reply_markup=menu_markup)


@bot.message_handler(commands=['balance'])
def handle_balance(message):
    bot.send_message(message.chat.id, "🔍 Запрашиваю балансы с SafeTrade...")
    balance_info = get_balances_safetrade()
    send_long_message(message.chat.id, balance_info, parse_mode='Markdown')


@bot.message_handler(commands=['sell_qtc'])
def handle_sell(message):
    bot.send_message(message.chat.id, f"Ищу `{CURRENCY_TO_SELL}` на балансе...", parse_mode='Markdown')
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
            send_long_message(message.chat.id, f"✅ Обнаружено `{qtc_balance}` {CURRENCY_TO_SELL}. Создаю ордер...", parse_mode='Markdown')
            sell_result = create_sell_order_safetrade(qtc_balance)
            send_long_message(message.chat.id, sell_result, parse_mode='Markdown')
        else:
            send_long_message(message.chat.id, f"Баланс `{CURRENCY_TO_SELL}` равен `{qtc_balance}`. Продавать нечего.", parse_mode='Markdown')
    except Exception as e:
        error_message = f"❌ Ошибка перед созданием ордера: {e}"
        if hasattr(e, 'response') and e.response is not None:
            response_text_truncated = e.response.text[:1000] + "..."
            error_message += f"\nОтвет сервера: `{response_text_truncated}`"
        send_long_message(message.chat.id, error_message, parse_mode='Markdown')


@bot.message_handler(commands=['history'])
def handle_history(message):
    bot.send_message(message.chat.id, "🔍 Запрашиваю историю ордеров...")
    orders = get_order_history(limit=10)
    if orders and isinstance(orders, list):
        if not orders:
            send_long_message(message.chat.id, "История исполненных ордеров пуста.")
            return
            
        history_text = "📊 *История последних исполненных ордеров:*\n\n"
        for order in orders:
            order_id = order.get('id', 'N/A')
            created_at = order.get('created_at', 'N/A')
            try:
                dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                formatted_time = created_at
            
            amount_str = f"`{order.get('amount', 'N/A')}`"
            price_str = f"`{order.get('price', 'N/A')}`"
            total_str = f"`{order.get('total', 'N/A')}`"

            trades = get_order_trades(order_id)
            if trades and isinstance(trades, list):
                total_amount_executed = sum(float(trade.get('amount', 0)) for trade in trades)
                total_sum_received = sum(float(trade.get('total', 0)) for trade in trades)
                avg_price_executed = total_sum_received / total_amount_executed if total_amount_executed > 0 else 0
                amount_str = f"`{total_amount_executed:.8f}`"
                price_str = f"`{avg_price_executed:.8f}` (средняя)"
                total_str = f"`{total_sum_received:.8f}`"

            history_text += (
                f"*ID ордера:* `{order_id}`\n"
                f"*Пара:* `{order.get('market', 'N/A').upper()}`\n"
                f"*Сторона:* `{order.get('side', 'N/A').capitalize()}`\n"
                f"*Объем:* {amount_str} {CURRENCY_TO_SELL}\n"
                f"*Цена:* {price_str} {CURRENCY_TO_BUY}\n"
                f"*Сумма:* {total_str} {CURRENCY_TO_BUY}\n"
                f"*Статус:* `{order.get('state', 'N/A').capitalize()}`\n"
                f"*Время:* `{formatted_time}`\n\n"
            )
        send_long_message(message.chat.id, history_text, parse_mode='Markdown')
    else:
        send_long_message(message.chat.id, "История ордеров пуста или произошла ошибка.")


@bot.message_handler(commands=['donate'])
def handle_donate(message):
    donate_markup = types.InlineKeyboardMarkup()
    donate_button = types.InlineKeyboardButton(text="Поддержать автора ❤️", url=DONATE_URL)
    donate_markup.add(donate_button)
    send_long_message(
        message.chat.id,
        "Если вы хотите поддержать разработку этого бота, вы можете сделать пожертвование. Спасибо!",
        reply_markup=donate_markup
    )


# --- Основной цикл бота (с защитой от ошибок) ---
if __name__ == "__main__":
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print("[CRITICAL] Не все переменные окружения установлены! Проверьте .env файл.")
    else:
        try:
            ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
            print("Бот SafeTrade запускается...")
            
            # Гарантированно очищаем старые подключения перед стартом
            try:
                print("Удаляю предыдущий вебхук для избежания конфликтов...")
                bot.remove_webhook()
                time.sleep(1)
                print("Вебхук успешно удален.")
            except Exception as e:
                print(f"Не удалось удалить вебхук (это нормально, если он не был установлен): {e}")
            
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            send_long_message(
                ADMIN_CHAT_ID,
                f"✅ *Бот SafeTrade успешно запущен!*\n\n*Время:* `{start_time}`\nОжидаю команды...",
                parse_mode='Markdown'
            )
            print(f"Уведомление о запуске отправлено администратору (ID: {ADMIN_CHAT_ID})")
            
            print("Планирую первую автоматическую продажу через 30 секунд...")
            threading.Timer(30, auto_sell_qtc).start()

            print("Бот начинает опрос Telegram API...")
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
            # Этот блок гарантирует корректное завершение работы
            print("Завершение работы бота. Отключаю polling...")
            bot.stop_polling()
            print("Polling остановлен. Бот выключен.")
