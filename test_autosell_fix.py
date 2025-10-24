#!/usr/bin/env python3
"""
Тестовый скрипт для проверки исправлений автопродажи
"""

import sys
import os
import logging
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_autosell_fix():
    """Тестируем исправления автопродажи"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            get_sellable_balances, 
            prioritize_sales, 
            execute_market_sell,
            auto_sell_all_altcoins,
            EASY_MODE
        )
        
        logging.info("🔧 Тестирование исправлений автопродажи")
        logging.info(f"📊 Режим работы: {'Простой режим' if EASY_MODE else 'Продвинутый режим'}")
        
        # 1. Проверяем получение балансов
        logging.info("1️⃣ Проверка получения балансов...")
        balances = get_sellable_balances()
        
        if not balances:
            logging.warning("❌ Нет балансов для продажи")
            return False
        
        logging.info(f"✅ Найдены балансы: {list(balances.keys())}")
        
        # 2. Проверяем приоритизацию
        logging.info("2️⃣ Проверка приоритизации...")
        priority_scores = prioritize_sales(balances)
        
        if not priority_scores:
            logging.warning("❌ Нет валют для продажи")
            return False
        
        logging.info(f"✅ Приоритезировано {len(priority_scores)} валют")
        for score in priority_scores[:3]:  # Показываем топ-3
            logging.info(f"   • {score.currency}: {score.balance} (${score.usd_value:.2f})")
        
        # 3. Тестируем рыночную продажу для первой валюты
        if priority_scores:
            test_currency = priority_scores[0]
            logging.info(f"3️⃣ Тестирование рыночной продажи для {test_currency.currency}...")
            
            # В простом режиме тестируем execute_market_sell
            if EASY_MODE:
                market_symbol = f"{test_currency.currency.lower()}usdt"
                success = execute_market_sell(market_symbol, test_currency.balance)
                
                if success:
                    logging.info(f"✅ Тестовая продажа {test_currency.currency} успешна")
                else:
                    logging.error(f"❌ Тестовая продажа {test_currency.currency} не удалась")
                    return False
            else:
                logging.info("📊 В продвинутом режиме пропускаем тестовую продажу")
        
        # 4. Проверяем полную автопродажу (только если есть балансы)
        logging.info("4️⃣ Проверка полной автопродажи...")
        result = auto_sell_all_altcoins()
        
        if result["success"]:
            logging.info(f"✅ Автопродажа успешна: {result['message']}")
            logging.info(f"   • Обработано: {result['total_processed']}")
            logging.info(f"   • Успешно: {result['successful_sales']}")
            logging.info(f"   • Ошибки: {result['failed_sales']}")
            return True
        else:
            logging.error(f"❌ Автопродажа не удалась: {result['message']}")
            return False
            
    except Exception as e:
        logging.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск теста исправлений автопродажи...")
    success = test_autosell_fix()
    
    if success:
        print("✅ Тест пройден успешно!")
        sys.exit(0)
    else:
        print("❌ Тест не пройден!")
        sys.exit(1)