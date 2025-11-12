#!/usr/bin/env python3
"""
Точная проверка баланса NOCK и попытка продажи с разными суммами
"""

import os
import sys
import logging
from pathlib import Path

# Добавляем текущую директорию в путь для импорта модулей
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def check_nock_balance():
    """Проверяем точный баланс NOCK"""
    try:
        from main import api_client
        
        print("🔍 Проверяем точный баланс NOCK...")
        
        # Получаем все балансы
        balances = api_client.get_balances()
        
        if not balances:
            print("❌ Не удалось получить балансы")
            return None
        
        # Ищем баланс NOCK
        nock_balance = 0
        for balance in balances:
            if balance.get('currency', '').upper() == 'NOCK':
                nock_balance = float(balance.get('balance', 0))
                print(f"✅ Найден баланс NOCK: {nock_balance}")
                break
        
        if nock_balance <= 0:
            print("❌ Баланс NOCK равен нулю")
            return None
        
        return nock_balance
        
    except Exception as e:
        print(f"❌ Ошибка при проверке баланса: {e}")
        return None

def test_small_orders(nock_balance):
    """Тестируем создание ордеров с разными суммами"""
    try:
        from main import get_ticker_price, create_sell_order_safetrade
        
        print(f"\n🧪 Тестируем создание ордеров с разными суммами...")
        print(f"   Исходный баланс: {nock_balance}")
        
        # Получаем текущую цену
        current_price = get_ticker_price("nockusdt")
        if not current_price:
            print("❌ Не удалось получить цену NOCK")
            return False
        
        print(f"   Текущая цена: ${current_price}")
        
        # Пробуем разные суммы
        test_amounts = [
            nock_balance * 0.1,  # 10%
            nock_balance * 0.2,  # 20%
            nock_balance * 0.3,  # 30%
            nock_balance * 0.4,  # 40%
            nock_balance * 0.5,  # 50%
            nock_balance * 0.6,  # 60%
            nock_balance * 0.7,  # 70%
            nock_balance * 0.8,  # 80%
            nock_balance * 0.9,  # 90%
            nock_balance * 0.95, # 95%
        ]
        
        for i, amount in enumerate(test_amounts):
            print(f"\n{i+1}. Пробуем продать {amount:.6f} NOCK (${amount * current_price:.4f})...")
            
            try:
                result = create_sell_order_safetrade("nockusdt", amount, "market")
                
                if result and isinstance(result, str) and "✅" in result:
                    print(f"✅ Успешно создан ордер на {amount:.6f} NOCK")
                    print(f"   Ответ: {result}")
                    return True
                else:
                    print(f"❌ Не удалось создать ордер: {result}")
            except Exception as e:
                print(f"❌ Ошибка при создании ордера: {e}")
                
                # Проверяем, есть ли информация об ошибке
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_details = e.response.json()
                        print(f"   Детали ошибки: {error_details}")
                    except:
                        print(f"   Текст ответа: {e.response.text}")
        
        print("\n❌ Не удалось создать ни одного ордера")
        return False
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании ордеров: {e}")
        return False

def test_very_small_order():
    """Тестируем создание очень маленького ордера"""
    try:
        from main import get_ticker_price, create_sell_order_safetrade
        
        print(f"\n🧪 Тестируем создание очень маленького ордера...")
        
        # Получаем текущую цену
        current_price = get_ticker_price("nockusdt")
        if not current_price:
            print("❌ Не удалось получить цену NOCK")
            return False
        
        print(f"   Текущая цена: ${current_price}")
        
        # Пробуем очень маленькую сумму
        small_amount = 0.01  # Минимальная сумма для NOCK
        print(f"   Пробуем продать {small_amount} NOCK (${small_amount * current_price:.4f})...")
        
        try:
            result = create_sell_order_safetrade("nockusdt", small_amount, "market")
            
            if result and isinstance(result, str) and "✅" in result:
                print(f"✅ Успешно создан ордер на {small_amount} NOCK")
                print(f"   Ответ: {result}")
                return True
            else:
                print(f"❌ Не удалось создать ордер: {result}")
        except Exception as e:
            print(f"❌ Ошибка при создании ордера: {e}")
            
            # Проверяем, есть ли информация об ошибке
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    print(f"   Детали ошибки: {error_details}")
                except:
                    print(f"   Текст ответа: {e.response.text}")
        
        return False
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании маленького ордера: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Запуск точной проверки баланса NOCK")
    print("=" * 60)
    
    # Проверяем баланс
    nock_balance = check_nock_balance()
    if not nock_balance:
        print("❌ Не удалось получить баланс NOCK")
        sys.exit(1)
    
    # Тестируем очень маленький ордер
    if not test_very_small_order():
        print("❌ Не удалось создать даже самый маленький ордер")
        sys.exit(1)
    
    # Тестируем ордера разного размера
    if not test_small_orders(nock_balance):
        print("❌ Не удалось создать ни один ордер")
        sys.exit(1)
    
    print("\n✅ Тестирование завершено успешно!")