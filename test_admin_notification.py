#!/usr/bin/env python3
"""
Тестовый скрипт для проверки отправки уведомлений администратору
"""
import os
import telebot
from dotenv import load_dotenv
from datetime import datetime

# Загружаем переменные окружения
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

def test_admin_notification():
    """Тестирует отправку уведомления администратору"""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не найден")
        return False
    
    if not ADMIN_CHAT_ID:
        print("❌ SAFETRADE_ADMIN_CHAT_ID не найден")
        return False
    
    try:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
        
        test_message = (
            f"🧪 **Тестовое уведомление администратора**\n\n"
            f"📅 **Время:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🤖 **Статус:** Тестирование уведомлений\n"
            f"✅ **Результат:** Сообщение успешно доставлено!\n\n"
            f"Это тестовое сообщение для проверки работы уведомлений администратора."
        )
        
        bot.send_message(
            ADMIN_CHAT_ID,
            test_message,
            parse_mode='Markdown'
        )
        
        print(f"✅ Тестовое сообщение отправлено администратору (ID: {ADMIN_CHAT_ID})")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Тестирование уведомлений администратора...")
    print(f"📱 Telegram Bot Token: {'✅' if TELEGRAM_BOT_TOKEN else '❌'}")
    print(f"👤 Admin Chat ID: {'✅' if ADMIN_CHAT_ID else '❌'}")
    
    if TELEGRAM_BOT_TOKEN and ADMIN_CHAT_ID:
        success = test_admin_notification()
        if success:
            print("\n🎉 Тест успешно пройден! Уведомления администратору работают.")
        else:
            print("\n❌ Тест не пройден. Проверьте настройки.")
    else:
        print("\n❌ Необходимые переменные окружения не настроены.")