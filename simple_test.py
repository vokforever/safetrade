#!/usr/bin/env python3
"""
Простой тест для проверки API
"""

import os
import sys
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Проверяем переменные окружения
print("Проверка переменных окружения:")
print(f"SAFETRADE_API_KEY: {'✅' if os.getenv('SAFETRADE_API_KEY') else '❌'}")
print(f"SAFETRADE_API_SECRET: {'✅' if os.getenv('SAFETRADE_API_SECRET') else '❌'}")
print(f"SUPABASE_URL: {'✅' if os.getenv('SUPABASE_URL') else '❌'}")
print(f"SUPABASE_KEY: {'✅' if os.getenv('SUPABASE_KEY') else '❌'}")

# Пробуем импортировать main
try:
    import main
    print("✅ Модуль main успешно импортирован")
    
    # Проверяем API клиент
    if hasattr(main, 'api_client') and main.api_client:
        print("✅ API клиент инициализирован")
        
        # Пробуем получить балансы
        try:
            balances = main.get_sellable_balances()
            if balances:
                print(f"✅ Балансы получены: {list(balances.keys())}")
                if 'NOCK' in balances:
                    print(f"✅ NOCK баланс: {balances['NOCK']}")
                else:
                    print("❌ NOCK не найден в балансах")
            else:
                print("❌ Не удалось получить балансы")
        except Exception as e:
            print(f"❌ Ошибка при получении балансов: {e}")
    else:
        print("❌ API клиент не инициализирован")
        
except Exception as e:
    print(f"❌ Ошибка при импорте main: {e}")
    import traceback
    traceback.print_exc()