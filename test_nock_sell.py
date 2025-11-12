#!/usr/bin/env python3
"""
Тестовый скрипт для проверки продажи NOCK
"""

import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_nock_sell():
    """Тестируем продажу NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            get_sellable_balances, 
            prioritize_sales, 
            execute_market_sell,
            create_sell_order_safetrade,
            api_client
        )
        
        logging.info("🔧 Тестирование продажи NOCK")
        
        # 1. Проверяем получение балансов
        logging.info("1️⃣ Проверка получения балансов...")
        balances = get_sellable_balances()
        
        if not balances:
            logging.warning("❌ Нет балансов для продажи")
            return False
        
        logging.info(f"✅ Найдены балансы: {list(balances.keys())}")
        
        # 2. Проверяем наличие NOCK
        if 'NOCK' not in balances:
            logging.warning("❌ NOCK не найден в балансах")
            return False
        
        nock_balance = balances['NOCK']
        logging.info(f"✅ Найден баланс NOCK: {nock_balance}")
        
        # 3. Тестируем прямое создание ордера для NOCK
        logging.info("3️⃣ Тестирование создания ордера для NOCK...")
        market_symbol = "nockusdt"
        
        # Сначала пробуем с правильной точностью из API
        try:
            # Импортируем функцию округления
            from main import round_amount_for_market
            
            # Округляем до правильной точности
            rounded_amount = round_amount_for_market(market_symbol, nock_balance)
            
            if rounded_amount is None:
                logging.error("❌ Не удалось округлить сумму до допустимой точности")
                return False
                
            logging.info(f"Пробуем с правильной точностью из API: {rounded_amount}")
            
            # Создаем ордер
            result = create_sell_order_safetrade(
                market_symbol=market_symbol,
                amount=rounded_amount,
                order_type="market"
            )
            
            if result and "✅" in result:
                logging.info(f"✅ Успешно создан ордер с правильной точностью")
                logging.info(f"Результат: {result}")
                return True
            else:
                logging.warning(f"Не удалось создать ордер с правильной точностью: {result}")
                
        except Exception as e:
            logging.warning(f"Ошибка при создании ордера с правильной точностью: {e}")
        
        # Если не получилось с правильной точностью, пробуем разные уровни
        precision_levels = [8, 7, 6, 5, 4, 3, 2]
        
        for precision in precision_levels:
            try:
                # Форматируем с новым уровнем точности
                formatted_amount = f"{nock_balance:.{precision}f}"
                rounded_amount = float(formatted_amount)
                
                logging.info(f"Пробуем точность {precision}: {rounded_amount}")
                
                # Создаем ордер
                result = create_sell_order_safetrade(
                    market_symbol=market_symbol,
                    amount=rounded_amount,
                    order_type="market"
                )
                
                if result and "✅" in result:
                    logging.info(f"✅ Успешно создан ордер с точностью {precision}")
                    logging.info(f"Результат: {result}")
                    return True
                else:
                    logging.warning(f"Не удалось создать ордер с точностью {precision}: {result}")
                    
            except Exception as precision_error:
                logging.warning(f"Ошибка при создании ордера с точностью {precision}: {precision_error}")
                continue
        
        # Если ни один уровень точности не сработал
        logging.error("❌ Не удалось создать ордер для NOCK - ни один уровень точности не подошел")
        return False
            
    except Exception as e:
        logging.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск теста продажи NOCK...")
    success = test_nock_sell()
    
    if success:
        print("✅ Тест пройден успешно!")
        sys.exit(0)
    else:
        print("❌ Тест не пройден!")
        sys.exit(1)