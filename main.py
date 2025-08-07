import time
import hmac
import hashlib
import binascii
import json
import os
import sys
import signal
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

BASE_URL = "https://safe.trade/api/v2"
CURRENCY_TO_SELL = "QTC"
CURRENCY_TO_BUY = "USDT"
MARKET_SYMBOL = f"{CURRENCY_TO_SELL.lower()}{CURRENCY_TO_BUY.lower()}"
MIN_SELL_AMOUNT = 0.00000001

# --- ИНИЦИАЛИЗАЦИЯ ---
def create_enhanced_scraper():
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

# --- Функции API SafeTrade ---
def generate_signature(nonce, secret, key):
    hash_obj = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    hash_obj.update((nonce + key).encode())
    signature = hash_obj.digest()
    signature_hex = binascii.hexlify(signature).decode()
    return signature_hex

def get_auth_headers():
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

# --- РАДИКАЛЬНАЯ ОЧИСТКА ВСЕХ ЭКЗЕМПЛЯРОВ БОТА ---
def force_cleanup_all_instances():
    """Радикальная очистка всех возможных экземпляров бота"""
    print("🔄 НАЧИНАЮ РАДИКАЛЬНУЮ ОЧИСТКУ ВСЕХ ЭКЗЕМПЛЯРОВ БОТА...")
    
    # 1. Удаляем вебхук несколько раз с разными интервалами
    for i in range(3):
        try:
            bot.remove_webhook()
            print(f"✅ Вебхук удален (попытка {i+1})")
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Ошибка удаления вебхука (попытка {i+1}): {e}")
    
    # 2. Сбрасываем вебхук
    try:
        bot.set_webhook()
        print("✅ Вебхук сброшен")
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Ошибка сброса вебхука: {e}")
    
    # 3. Многократно очищаем все ожидающие обновления
    for i in range(5):
        try:
            updates = bot.get_updates()
            if updates:
                last_update_id = updates[-1].update_id
                bot.get_updates(offset=last_update_id + 1)
                print(f"✅ Очищено {len(updates)} обновлений (попытка {i+1})")
            else:
                print(f"✅ Нет ожидающих обновлений (попытка {i+1})")
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Ошибка очистки обновлений (попытка {i+1}): {e}")
    
    # 4. Убиваем все процессы Python с похожими именами
    try:
        import psutil
        current_pid = os.getpid()
        killed_count = 0
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # Пропускаем текущий процесс
                if proc.info['pid'] == current_pid:
                    continue
                
                # Ищем процессы Python
                if 'python' in proc.info['name'].lower():
                    cmdline = proc.info.get('cmdline', [])
                    cmdline_str = ' '.join(str(cmd) for cmd in cmdline)
                    
                    # Убиваем процессы, связанные с нашим ботом
                    if any(keyword in cmdline_str.lower() for keyword in ['safetrade', 'telegram', 'bot']):
                        try:
                            proc.kill()
                            killed_count += 1
                            print(f"🔪 Убит процесс PID {proc.info['pid']}: {cmdline_str[:100]}...")
                        except:
                            try:
                                proc.terminate()
                                killed_count += 1
                                print(f"⚡ Завершен процесс PID {proc.info['pid']}: {cmdline_str[:100]}...")
                            except:
                                print(f"❌ Не удалось убить процесс PID {proc.info['pid']}")
                        
                        time.sleep(0.5)  # Небольшая задержка между убийствами процессов
            
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        if killed_count > 0:
            print(f"🔪 Всего убито/завершено процессов: {killed_count}")
            time.sleep(3)  # Даем время на завершение процессов
        else:
            print("✅ Дополнительные процессы не найдены")
            
    except ImportError:
        print("⚠️ psutil не установлен, пропускаю убийство процессов")
    
    # 5. Дополнительная очистка через API Telegram
    try:
        # Получаем информацию о боте
        bot_info = bot.get_me()
        print(f"✅ Информация о боте получена: @{bot_info.username}")
        
        # Финальная очистка обновлений
        updates = bot.get_updates()
        if updates:
            last_update_id = updates[-1].update_id
            bot.get_updates(offset=last_update_id + 1)
            print(f"✅ Финальная очистка: удалено {len(updates)} обновлений")
        
    except Exception as e:
        print(f"⚠️ Ошибка при финальной очистке: {e}")
    
    print("✅ РАДИКАЛЬНАЯ ОЧИСТКА ЗАВЕРШЕНА")

# --- Обработчики команд Telegram ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    welcome_text = """
👋 *Добро пожаловать в бот для управления биржей SafeTrade!*
*Доступные команды:*
✅ `/start` - Показать это приветственное сообщение.
💰 `/balance` - Показать ненулевые балансы.
📉 `/sell_qtc` - Продать весь доступный баланс QTC за USDT.
❤️ `/donate` - Поддержать автора.
"""
    send_long_message(message.chat.id, text=welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['balance'])
def handle_balance(message):
    bot.send_message(message.chat.id, "🔍 Запрашиваю балансы с SafeTrade...")
    balance_info = get_balances_safetrade()
    send_long_message(message.chat.id, balance_info, parse_mode='Markdown')

@bot.message_handler(commands=['cleanup'])
def handle_cleanup(message):
    """Команда для ручной очистки конфликтов"""
    if str(message.chat.id) == str(ADMIN_CHAT_ID):
        bot.send_message(message.chat.id, "🔄 Начинаю принудительную очистку...")
        force_cleanup_all_instances()
        bot.send_message(message.chat.id, "✅ Очистка завершена!")
    else:
        bot.send_message(message.chat.id, "❌ У вас нет прав для выполнения этой команды.")

# --- Функция для отправки длинных сообщений ---
def send_long_message(chat_id, text, **kwargs):
    if not text:
        return
    MAX_MESSAGE_LENGTH = 4000
    if len(text) <= MAX_MESSAGE_LENGTH:
        try:
            bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            print(f"Ошибка при отправке сообщения: {e}")
        return
    
    # Разбиваем длинное сообщение
    parts = [text[i:i+MAX_MESSAGE_LENGTH] for i in range(0, len(text), MAX_MESSAGE_LENGTH)]
    for part in parts:
        try:
            bot.send_message(chat_id, part, **kwargs)
            time.sleep(0.1)  # Небольшая задержка между частями
        except Exception as e:
            print(f"Ошибка при отправке части сообщения: {e}")

# --- Обработчик сигналов для корректного завершения ---
def signal_handler(sig, frame):
    print(f"\n🛑 Получен сигнал {sig}, завершаю работу...")
    try:
        bot.stop_polling()
    except:
        pass
    sys.exit(0)

# --- Основной цикл бота ---
if __name__ == "__main__":
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID]):
        print("[CRITICAL] Не все переменные окружения установлены! Проверьте .env файл.")
        sys.exit(1)
    
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
        print("🚀 Бот SafeTrade запускается...")
        print(f"📍 Используемый BASE_URL: {BASE_URL}")
        
        # РАДИКАЛЬНАЯ ОЧИСТКА ПЕРЕД ЗАПУСКОМ
        force_cleanup_all_instances()
        
        # Дополнительная пауза для гарантии очистки
        time.sleep(2)
        
        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            send_long_message(
                ADMIN_CHAT_ID,
                f"✅ *Бот SafeTrade успешно запущен!*\n\n"
                f"*Время:* `{start_time}`\n"
                f"*BASE_URL:* `{BASE_URL}`\n"
                f"*PID:* `{os.getpid()}`\n"
                f"Ожидаю команды...",
                parse_mode='Markdown'
            )
            print(f"✅ Уведомление о запуске отправлено администратору (ID: {ADMIN_CHAT_ID})")
        except Exception as e:
            print(f"⚠️ Не удалось отправить уведомление: {e}")
        
        print("🔄 Бот начинает опрос Telegram API...")
        
        # Используем infinity_polling с обработкой ошибок
        while True:
            try:
                bot.infinity_polling(timeout=20, long_polling_timeout=30)
                break  # Если polling завершился нормально, выходим из цикла
            except Exception as e:
                print(f"❌ Ошибка в infinity_polling: {e}")
                print("🔄 Пытаюсь перезапустить polling через 5 секунд...")
                time.sleep(5)
                
                # Перед перезапуском снова очищаем
                force_cleanup_all_instances()
                print("🔄 Очистка завершена, перезапускаю polling...")
        
    except ValueError:
        print("[CRITICAL] ADMIN_CHAT_ID в .env файле должен быть числом!")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Критическая ошибка при запуске бота: {e}")
        if ADMIN_CHAT_ID:
            try:
                send_long_message(ADMIN_CHAT_ID, f"❌ *Критическая ошибка при запуске бота!*\n\n`{e}`", parse_mode='Markdown')
            except Exception as notify_err:
                print(f"Не удалось отправить уведомление об ошибке администратору: {notify_err}")
        sys.exit(1)
    finally:
        print("🛑 Завершение работы бота. Отключаю polling...")
        try:
            bot.stop_polling()
        except:
            pass
        print("✅ Polling остановлен. Бот выключен.")
