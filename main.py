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

# НОВАЯ ФУНКЦИЯ: Получение текущей рыночной цены (бид)
def get_current_bid_price(market_symbol):
    """
    Получает текущую лучшую цену покупки (бид) для указанной торговой пары.
    ЭТО ПРИМЕРНАЯ РЕАЛИЗАЦИЯ. ВАМ НУЖНО УТОЧНИТЬ ЭНДПОИНТ И СТРУКТУРУ ОТВЕТА
    В СООТВЕТСТВИИ С ДОКУМЕНТАЦИЕЙ SAFETRADE API.
    Предполагаемый эндпоинт: /trade/public/tickers/{market_id}
    """
    path = f"/trade/public/tickers/{market_symbol}"
    url = BASE_URL + path
    try:
        # Для публичных эндпоинтов заголовки аутентификации обычно не нужны
        response = scraper.get(url)
        response.raise_for_status()
        ticker_data = response.json()
        
        # Предполагаем, что 'bid' содержит лучшую цену покупки
        # Если SafeTrade возвращает список, найдите нужный тикер.
        # Если возвращается объект, обратитесь напрямую.
        if isinstance(ticker_data, dict) and 'bid' in ticker_data:
            return float(ticker_data['bid'])
        elif isinstance(ticker_data, list):
            # Если ответ - список тикеров, найдем наш
            for ticker in ticker_data:
                if ticker.get('market') == market_symbol:
                    if 'bid' in ticker:
                        return float(ticker['bid'])
            print(f"Не найдена информация о биде для {market_symbol} в списке тикеров.")
            return None
        else:
            print(f"Неожиданный формат данных тикера: {ticker_data}")
            return None
    except Exception as e:
        print(f"Ошибка при получении текущей цены бида для {market_symbol}: {e}")
        # В случае ошибки, можно вернуть очень низкую цену, чтобы ордер исполнился,
        # но это рискованно. Лучше уведомить пользователя.
        return None

def create_sell_order_safetrade(amount):
    """
    Создает ордер на продажу и возвращает отформатированный результат.
    Использует ЛИМИТНЫЙ ОРДЕР, имитируя рыночный.
    """
    path = "/trade/market/orders"
    url = BASE_URL + path

    # ШАГ 1: Получаем текущую лучшую цену покупки (бид) для QTC/USDT
    current_bid_price = get_current_bid_price(MARKET_SYMBOL)

    if current_bid_price is None or current_bid_price <= 0:
        return (
            f"❌ Не удалось получить актуальную цену для {CURRENCY_TO_SELL}/{CURRENCY_TO_BUY}. "
            f"Невозможно создать лимитный ордер на продажу. "
            f"Попробуйте позже или проверьте соединение/API."
        )

    # ШАГ 2: Определяем цену для лимитного ордера.
    # Чтобы гарантировать немедленное исполнение (имитация рыночного ордера),
    # мы устанавливаем цену, равную текущему биду, или чуть ниже.
    # Если стакан достаточно глубокий, ордер будет исполнен сразу по лучшим ценам.
    # Если вы хотите быть более агрессивным, можно поставить цену немного ниже бида.
    # Например, current_bid_price * 0.999 (чтобы продать на 0.1% ниже бида)
    # Для максимальной гарантии исполнения по любой доступной цене,
    # можно установить очень низкую цену (например, 0.00000001), но это крайне не рекомендуется,
    # так как вы можете продать намного дешевле, чем могли бы.
    # Оптимально - использовать текущий бид.
    price_to_sell_at = current_bid_price # Продаем по текущей лучшей цене покупки

    payload = {
        "market": MARKET_SYMBOL,
        "side": "sell",
        "type": "limit",  # ИЗМЕНЕНО: теперь это 'limit' ордер
        "amount": str(amount),
        "price": str(price_to_sell_at)  # НОВОЕ: добавлен параметр price
    }

    try:
        headers = get_auth_headers()
        response = scraper.post(url, headers=headers, json=payload)
        response.raise_for_status()
        order_details = response.json()

        order_id = order_details.get('id')
        # В случае лимитного ордера, amount в ответе может отличаться от заявленного,
        # если ордер исполнен частично. Но для первоначального отображения используем заявленный.
        order_amount_displayed = order_details.get('amount', amount)
        order_price_displayed = order_details.get('price', price_to_sell_at)

        if order_id:
            # Запускаем отслеживание ордера в отдельном потоке
            threading.Thread(target=track_order, args=(order_id,)).start()

        return (
            f"✅ *Успешно размещен ордер на продажу!*\n\n"
            f"*Биржа:* SafeTrade\n"
            f"*Пара:* `{order_details.get('market', 'N/A').upper()}`\n"
            f"*Тип:* `{order_details.get('type', 'N/A').capitalize()}`\n"
            f"*Сторона:* `{order_details.get('side', 'N/A').capitalize()}`\n"
            f"*Заявленный объем:* `{order_amount_displayed} {CURRENCY_TO_SELL}`\n"
            f"*Заданная цена:* `{order_price_displayed} {CURRENCY_TO_BUY}`\n" # Теперь отображаем заданную цену
            f"*ID ордера:* `{order_id}`"
        )
    except Exception as e:
        error_message = f"❌ Ошибка при создании ордера на продажу на SafeTrade: {e}"
        if hasattr(e, 'response') and e.response is not None:
            # Ответ сервера теперь выводится в Markdown для лучшего форматирования
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
        params = {"order_id": str(order_id)} # Фильтруем по ID ордера
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
        # Изменил state на "done", "active", "cancel", или можно не указывать, чтобы получить все
        # Для истории обычно нужны "done" и "cancel"
        params = {"market": MARKET_SYMBOL, "limit": limit, "state": "done"}
        response = scraper.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении истории ордеров: {e}")
        return []


def track_order(order_id):
    """Отслеживает статус ордера и уведомляет о его исполнении."""
    max_attempts = 30 # Максимальное количество попыток проверки
    check_interval = 10 # Интервал между проверками в секундах

    for attempt in range(max_attempts):
        time.sleep(check_interval)
        order_info = get_order_info(order_id)

        if not order_info:
            print(f"Попытка {attempt+1}/{max_attempts}: Не удалось получить информацию об ордере {order_id}.")
            continue # Продолжаем попытки, если информация не получена

        order_state = order_info.get('state')
        print(f"Попытка {attempt+1}/{max_attempts}: Ордер {order_id} в состоянии: {order_state}")

        if order_state == 'done':
            # Ордер полностью исполнен
            trades = get_order_trades(order_id)
            if trades:
                total_amount = sum(float(trade.get('amount', 0)) for trade in trades)
                total_sum = sum(float(trade.get('total', 0)) for trade in trades)
                avg_price = total_sum / total_amount if total_amount > 0 else 0
                executed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # Время уведомления

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
                    print(f"Уведомление об исполнении ордера {order_id} отправлено.")
                except Exception as e:
                    print(f"Ошибка отправки уведомления об исполнении ордера: {e}")
                return # Завершаем отслеживание
        elif order_state == 'cancel':
            # Ордер отменен
            message = (
                f"❌ *Ордер отменен!*\n\n"
                f"*ID ордера:* `{order_id}`\n"
                f"*Пара:* `{MARKET_SYMBOL.upper()}`\n"
                f"*Время отмены:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            )
            try:
                bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
                print(f"Уведомление об отмене ордера {order_id} отправлено.")
            except Exception as e:
                print(f"Ошибка отправки уведомления об отмене ордера: {e}")
            return # Завершаем отслеживание
        elif order_state == 'pending':
            # Ордер еще не исполнен, продолжаем отслеживание
            print(f"Ордер {order_id} все еще в состоянии 'pending'.")
            # Можно добавить логику для частичного исполнения, если SafeTrade поддерживает
            # partial fill для 'pending' state
        elif order_state == 'active':
             # Ордер активен, но не полностью исполнен. Это может быть частично исполненный лимитный ордер.
            print(f"Ордер {order_id} активен (active).")
            # Продолжаем ждать 'done' или 'cancel'
        else:
            print(f"Неизвестное состояние ордера {order_id}: {order_state}")


    # Если вышли из цикла по истечении попыток, но ордер не исполнен/отменен
    print(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток. Ордер не перешел в состояние 'done' или 'cancel'.")
    final_order_info = get_order_info(order_id)
    if final_order_info and final_order_info.get('state') != 'done' and final_order_info.get('state') != 'cancel':
        message = (
            f"⚠️ *Отслеживание ордера завершено без окончательного статуса!*\n\n"
            f"*ID ордера:* `{order_id}`\n"
            f"*Последний известный статус:* `{final_order_info.get('state', 'N/A').capitalize()}`\n"
            f"Пожалуйста, проверьте статус ордера вручную на SafeTrade."
        )
        try:
            bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
        except Exception as e:
            print(f"Ошибка отправки предупреждения о незавершенном отслеживании: {e}")


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
📉 `/sell_qtc` - Создать лимитный ордер на продажу *всего доступного* баланса QTC за USDT по текущей рыночной цене.
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
        
        # Проверяем, что баланс QTC достаточно большой для продажи (например, больше минимального размера ордера)
        # Это предотвратит отправку ордеров с очень маленьким объемом, которые могут быть отклонены биржей
        MIN_SELL_AMOUNT = 0.001 # Примерное минимальное количество, уточните в документации SafeTrade
        if qtc_balance > MIN_SELL_AMOUNT:
            bot.send_message(message.chat.id,
                             f"✅ Обнаружено `{qtc_balance}` {CURRENCY_TO_SELL}. Создаю ордер на продажу...",
                             parse_mode='Markdown')
            sell_result = create_sell_order_safetrade(qtc_balance)
            bot.send_message(message.chat.id, sell_result, parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, f"Баланс `{CURRENCY_TO_SELL}` равен `{qtc_balance}`. "
                                             f"Продавать нечего или объем слишком мал (мин. `{MIN_SELL_AMOUNT}`).",
                             parse_mode='Markdown')
    except Exception as e:
        error_message = f"❌ Произошла ошибка при подготовке к созданию ордера: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nОтвет сервера: `{e.response.text}`"
        bot.send_message(message.chat.id, error_message)


@bot.message_handler(commands=['history'])
def handle_history(message):
    """Обработчик команды /history с корректным отображением исполненных ордеров."""
    bot.send_message(message.chat.id, "🔍 Запрашиваю историю ордеров с SafeTrade...")

    orders = get_order_history(limit=10) # Получаем последние 10 исполненных ордеров

    if orders and isinstance(orders, list) and len(orders) > 0:
        history_text = "📊 *История ваших последних исполненных ордеров:*\n\n"
        for order in orders:
            order_id = order.get('id', 'N/A')
            created_at = order.get('created_at', 'N/A')

            try:
                # Парсим дату и время для форматирования
                # Формат ISO 8601, который обычно используется API: YYYY-MM-DDTHH:MM:SS.fZ
                dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                formatted_time = created_at # Если формат не подходит, оставляем как есть

            # Инициализируем значения для отображения
            amount_str = f"`{order.get('amount', 'N/A')}`" # Запрошенный объем
            price_str = f"`{order.get('price', 'N/A')}`" # Запрошенная цена (для лимитного ордера)
            total_str = f"`{order.get('total', 'N/A')}`" # Общая сумма (для исполненного ордера)

            # Если ордер исполнен ('done'), получаем реальные данные о сделках
            if order.get('state') == 'done':
                trades = get_order_trades(order_id)
                if trades and isinstance(trades, list) and len(trades) > 0:
                    total_amount_executed = sum(float(trade.get('amount', 0)) for trade in trades)
                    total_sum_received = sum(float(trade.get('total', 0)) for trade in trades)
                    # Средняя цена исполнения
                    avg_price_executed = total_sum_received / total_amount_executed if total_amount_executed > 0 else 0

                    amount_str = f"`{total_amount_executed:.8f}`" # Фактически проданный объем
                    price_str = f"`{avg_price_executed:.8f}` (средняя)" # Средняя цена исполнения
                    total_str = f"`{total_sum_received:.8f}`" # Фактически полученная сумма

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
        bot.send_message(message.chat.id, "История исполненных ордеров пуста или произошла ошибка при получении.")


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
