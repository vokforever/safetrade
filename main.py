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
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # ID администратора для уведомлений (должен быть числом, например, "123456789")

# URL для пожертвований
DONATE_URL = "https://boosty.to/vokforever/donate"

# Убедимся, что секрет в байтовом представлении для hmac
# Проверка на None, чтобы избежать ошибки, если API_SECRET отсутствует
API_SECRET_BYTES = API_SECRET.encode('utf-8') if API_SECRET else None
BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}" # qtcudst

# Минимальный объем QTC для продажи. УТОЧНИТЕ ЭТО ЗНАЧЕНИЕ В ДОКУМЕНТАЦИИ SAFETRADE!
# Если вы попытаетесь продать меньше, биржа может отклонит ордер.
MIN_SELL_AMOUNT = 0.00000001 # Примерно, обычно 0.00000001 или 0.00001 и т.д.

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
    # Проверяем, что API_KEY и API_SECRET_BYTES не None
    if not API_KEY or not API_SECRET_BYTES:
        raise ValueError("API Key or API Secret is not set. Cannot generate authentication headers.")
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
        response.raise_for_status() # Вызывает исключение для HTTP ошибок 4xx/5xx
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
            error_message += f"\nОтвет сервера: `{e.response.text}`"
        return error_message


# --- ИСПРАВЛЕННАЯ ФУНКЦИЯ: Получение текущей рыночной цены (бид) ---
def get_current_bid_price(market_symbol):
    """
    Получает текущую лучшую цену покупки (бид) для указанной торговой пары.
    Использует эндпоинт /trade/public/tickers/{market} из документации SafeTrade API. [1]
    """
    path = f"/trade/public/tickers/{market_symbol}"
    url = BASE_URL + path
    try:
        # Для публичных эндпоинтов заголовки аутентификации не нужны
        response = scraper.get(url)
        response.raise_for_status() # Вызовет исключение для статусов 4xx/5xx
        ticker_data = response.json()

        # Ожидаем, что API вернет словарь с информацией о конкретном тикере,
        # содержащий ключ 'bid'
        if isinstance(ticker_data, dict) and 'bid' in ticker_data:
            return float(ticker_data['bid'])
        else:
            print(f"Неожиданный формат данных тикера для {market_symbol} от SafeTrade: {ticker_data}")
            return None
    except Exception as e:
        print(f"Ошибка при получении текущей цены бида для {market_symbol}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Ответ сервера (get_current_bid_price): {e.response.text}")
        return None # Важно вернуть None, если цену не удалось получить


def create_sell_order_safetrade(amount):
    """
    Создает ордер на продажу и возвращает отформатированный результат.
    Использует ЛИМИТНЫЙ ОРДЕР, имитируя рыночный, основываясь на текущей цене бида.
    """
    path = "/trade/market/orders"
    url = BASE_URL + path

    # ШАГ 1: Получаем текущую лучшую цену покупки (бид) для QTC/USDT
    current_bid_price = get_current_bid_price(MARKET_SYMBOL)

    if current_bid_price is None or current_bid_price <= 0:
        # Если не удалось получить цену или она недействительна, возвращаем ошибку
        return (
            f"❌ Не удалось получить актуальную цену для `{CURRENCY_TO_SELL}/{CURRENCY_TO_BUY}`. "
            f"Невозможно создать лимитный ордер на продажу. "
            f"Пожалуйста, проверьте логи бота или попробуйте позже."
        )

    # ШАГ 2: Определяем цену для лимитного ордера.
    # Для имитации рыночного ордера продаем по текущей лучшей цене покупки (бид).
    # Это обеспечит почти немедленное исполнение, если в стакане есть покупатели.
    price_to_sell_at = current_bid_price

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
        order_amount_displayed = order_details.get('amount', amount) # Отображаем запрошенный объем
        order_price_displayed = order_details.get('price', price_to_sell_at) # Отображаем заданную цену

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
            f"*Заданная цена:* `{order_price_displayed} {CURRENCY_TO_BUY}`\n"
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
    path = "/trade/market/trades" # Корректный эндпоинт [1]
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        # Добавляем фильтрацию по ID ордера
        params = {"order_id": str(order_id)}
        response = scraper.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении сделок по ордеру {order_id}: {e}")
        return []


def get_order_history(limit=10):
    """Получает историю ордеров с биржи (по умолчанию 10 последних исполненных)."""
    path = "/trade/market/orders"
    url = BASE_URL + path
    try:
        headers = get_auth_headers()
        # "done" для исполненных, "cancel" для отмененных. Можно убрать state, чтобы получить все.
        params = {"market": MARKET_SYMBOL, "limit": limit, "state": "done"}
        response = scraper.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка при получении истории ордеров: {e}")
        return []


def track_order(order_id):
    """Отслеживает статус ордера и уведомляет о его исполнении/отмене."""
    max_attempts = 30  # Максимальное количество попыток проверки
    check_interval = 10  # Интервал между проверками в секундах

    print(f"Начинаю отслеживание ордера {order_id}...")
    for attempt in range(max_attempts):
        time.sleep(check_interval)
        order_info = get_order_info(order_id)

        if not order_info:
            print(f"Попытка {attempt+1}/{max_attempts}: Не удалось получить информацию об ордере {order_id}. Продолжаю...")
            continue

        order_state = order_info.get('state')
        print(f"Попытка {attempt+1}/{max_attempts}: Ордер {order_id} в состоянии: '{order_state}'")

        if order_state == 'done':
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
                    print(f"Ошибка отправки уведомления об исполнении ордера {order_id}: {e}")
                return # Завершаем отслеживание
        elif order_state == 'cancel':
            message = (
                f"❌ *Ордер отменен!*\n\n"
                f"*ID ордера:* `{order_id}`\n"
                f"*Пара:* `{MARKET_SYMBOL.upper()}`\n"
                f"*Причина:* `{order_info.get('reason', 'N/A')}`\n" # Если API предоставляет причину отмены
                f"*Время отмены:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            )
            try:
                bot.send_message(ADMIN_CHAT_ID, message, parse_mode='Markdown')
            except Exception as e:
                print(f"Ошибка отправки уведомления об отмене ордера {order_id}: {e}")
            return # Завершаем отслеживание
        # Если ордер еще pending или active, продолжаем ждать
        elif order_state in ['pending', 'active']:
            # Можно добавить логику для частичного исполнения здесь, если нужно
            pass
        else:
            print(f"Неизвестное состояние ордера {order_id}: {order_state}")

    # Если вышли из цикла по истечении попыток, но ордер не исполнен/отменен
    print(f"Прекращено отслеживание ордера {order_id} после {max_attempts} попыток. Ордер не перешел в состояние 'done' или 'cancel'.")
    final_order_info = get_order_info(order_id)
    if final_order_info and final_order_info.get('state') not in ['done', 'cancel']:
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


# --- НОВАЯ ФУНКЦИЯ: Автоматическая продажа QTC ---
def auto_sell_qtc():
    """
    Функция для автоматической продажи QTC. Вызывается по расписанию.
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Запущена автоматическая проверка для продажи QTC...")
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
        
        if qtc_balance > MIN_SELL_AMOUNT:
            print(f"Обнаружен баланс {qtc_balance} {CURRENCY_TO_SELL}. Инициирую автоматическую продажу.")
            sell_result = create_sell_order_safetrade(qtc_balance)
            # Отправляем уведомление администратору об автоматической продаже
            bot.send_message(ADMIN_CHAT_ID, f"🔔 *Автоматическая продажа QTC по расписанию:*\n\n{sell_result}", parse_mode='Markdown')
        else:
            print(f"Баланс {CURRENCY_TO_SELL} ({qtc_balance}) слишком мал для автоматической продажи (мин. {MIN_SELL_AMOUNT}). Пропускаю.")
    except Exception as e:
        error_message = f"❌ *Произошла ошибка при попытке автоматической продажи QTC:* {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_message += f"\nОтвет сервера: `{e.response.text}`"
        bot.send_message(ADMIN_CHAT_ID, error_message, parse_mode='Markdown')
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error_message}")
    finally:
        # Планируем следующий запуск через 1 час (3600 секунд)
        # Это простой способ планирования, но он не переживает перезапуски бота.
        # Для более надежного планирования рассмотрите библиотеки вроде APScheduler.
        threading.Timer(3600, auto_sell_qtc).start()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Следующая автоматическая продажа запланирована через 1 час.")


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
        
        if qtc_balance > MIN_SELL_AMOUNT:
            bot.send_message(message.chat.id,
                             f"✅ Обнаружено `{qtc_balance}` {CURRENCY_TO_SELL}. Создаю лимитный ордер на продажу по рыночной цене...",
                             parse_mode='Markdown')
            sell_result = create_sell_order_safetrade(qtc_balance)
            bot.send_message(message.chat.id, sell_result, parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, f"Баланс `{CURRENCY_TO_SELL}` равен `{qtc_balance}`. "
                                             f"Продавать нечего или объем слишком мал (мин. `{MIN_SELL_AMOUNT}`).",
                             parse_mode='Markdown')
    except Exception as e:
        error_message = f"❌ Произошла ошибка перед созданием ордера: {e}"
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
                # Парсим дату и время для форматирования из ISO 8601
                dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                formatted_time = created_at # Если формат не подходит, оставляем как есть

            # Инициализируем значения для отображения, используя данные из самого ордера
            # (они могут быть неполными до полного исполнения)
            amount_str = f"`{order.get('amount', 'N/A')}`"
            price_str = f"`{order.get('price', 'N/A')}`"
            total_str = f"`{order.get('total', 'N/A')}`"

            # Если ордер полностью исполнен ('done'), получаем реальные данные о сделках
            if order.get('state') == 'done':
                trades = get_order_trades(order_id)
                if trades and isinstance(trades, list) and len(trades) > 0:
                    total_amount_executed = sum(float(trade.get('amount', 0)) for trade in trades)
                    total_sum_received = sum(float(trade.get('total', 0)) for trade in trades)
                    # Средняя цена исполнения
                    avg_price_executed = total_sum_received / total_amount_executed if total_amount_executed > 0 else 0

                    amount_str = f"`{total_amount_executed:.8f}`"
                    price_str = f"`{avg_price_executed:.8f}` (средняя)"
                    total_str = f"`{total_sum_received:.8f}`"

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
    # Проверяем наличие всех необходимых переменных окружения
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print(
            "[CRITICAL] Не все переменные окружения установлены! Проверьте SAFETRADE_API_KEY, SAFETRADE_API_SECRET, TELEGRAM_BOT_TOKEN и ADMIN_CHAT_ID в файле .env"
        )
    else:
        # Проверяем, что ADMIN_CHAT_ID можно привести к int
        try:
            ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
        except ValueError:
            print("[CRITICAL] ADMIN_CHAT_ID в .env файле должен быть числом!")
            exit()

        print("Бот SafeTrade запущен...")
        try:
            start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Отправляем уведомление администратору о запуске бота
            bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *Бот SafeTrade успешно запущен!*\n\n*Время запуска:* `{start_time}`\nОжидаю команды...",
                parse_mode='Markdown'
            )
            print(f"Уведомление о запуске отправлено администратору (Chat ID: {ADMIN_CHAT_ID})")
        except Exception as e:
            print(f"[WARNING] Не удалось отправить уведомление о запуске администратору. Ошибка: {e}")
            print("Возможно, TELEGRAM_BOT_TOKEN или ADMIN_CHAT_ID указаны неверно, или бот не имеет доступа к чату.")
        
        # Запускаем первую автоматическую продажу с небольшой задержкой (например, 30 секунд),
        # чтобы дать боту полностью инициализироваться.
        # Далее функция auto_sell_qtc будет сама себя планировать каждые 3600 секунд (1 час).
        print("Планирую первую автоматическую продажу QTC через 30 секунд...")
        threading.Timer(30, auto_sell_qtc).start()

        print("Бот начинает опрос Telegram API для получения команд...")
        # Запускаем бесконечный опрос Telegram API
        # ВНИМАНИЕ: Если вы видите ошибку 409 "Conflict: terminated by other getUpdates request",
        # это означает, что у вас запущено несколько экземпляров этого бота.
        # Остановите все дубликаты. Для продакшена лучше использовать webhooks.
        bot.infinity_polling()
