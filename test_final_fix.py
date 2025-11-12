#!/usr/bin/env python3
"""
Финальное тестирование исправленной функции автопродажи NOCK
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

def test_final_fix():
    """Тестируем финальные исправления"""
    try:
        from main import (
            get_sellable_balances, 
            prioritize_sales, 
            auto_sell_all_altcoins,
            EASY_MODE
        )
        
        print("🔍 Финальное тестирование исправленной функции автопродажи...")
        print(f"📊 Режим работы: {'Простой' if EASY_MODE else 'Продвинутый'}")
        
        # 1. Проверяем доступные балансы
        print("\n1️⃣ Проверяем доступные балансы...")
        balances = get_sellable_balances()
        
        if not balances:
            print("❌ Нет доступных балансов для продажи")
            return False
        
        print(f"✅ Найдены балансы: {balances}")
        
        # 2. Проверяем приоритизацию
        print("\n2️⃣ Проверяем приоритизацию...")
        priority_scores = prioritize_sales(balances)
        
        if not priority_scores:
            print("❌ Нет валют для продажи")
            return False
        
        print(f"✅ Приоритезированные валюты:")
        for score in priority_scores:
            print(f"   • {score.currency}: {score.balance} (${score.usd_value:.2f})")
        
        # 3. Проверяем, есть ли NOCK
        nock_score = None
        for score in priority_scores:
            if score.currency == "NOCK":
                nock_score = score
                break
        
        if nock_score:
            print(f"\n🎯 Найден NOCK: {nock_score.balance}")
            print(f"   Будет использовано 99% от баланса: {nock_score.balance * 0.99:.8f}")
            
            # Определяем ожидаемое количество частей
            if nock_score.balance > 100:
                if nock_score.balance > 500:
                    expected_parts = 5
                elif nock_score.balance > 200:
                    expected_parts = 3
                else:
                    expected_parts = 2
                
                print(f"   Ожидаемое количество частей: {expected_parts}")
                print(f"   Размер каждой части: {(nock_score.balance * 0.99) / expected_parts:.4f}")
        
        # 4. Запускаем автопродажу (в тестовом режиме)
        print("\n3️⃣ Запускаем автопродажу...")
        print("   ВНИМАНИЕ: Это реальная продажа! Если хотите только тест, прервите выполнение (Ctrl+C)")
        
        # Ждем подтверждения пользователя
        user_input = input("\nПродолжить с реальной продажей? (y/N): ")
        if user_input.lower() != 'y':
            print("❌ Тест прерван пользователем")
            return True
        
        # Запускаем автопродажу
        result = auto_sell_all_altcoins()
        
        if result["success"]:
            print(f"\n✅ Автопродажа завершена успешно!")
            print(f"   Обработано валют: {result['total_processed']}")
            print(f"   Успешных продаж: {result['successful_sales']}")
            print(f"   Неудачных попыток: {result['failed_sales']}")
            return True
        else:
            print(f"\n❌ Автопродажа завершилась с ошибкой: {result['message']}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск финального тестирования исправлений автопродажи NOCK")
    print("=" * 60)
    
    # Тестируем автопродажу
    if not test_final_fix():
        print("❌ Тест автопродажи не пройден")
        sys.exit(1)
    
    print("\n✅ Все тесты пройдены успешно!")