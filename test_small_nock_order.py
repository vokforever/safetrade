#!/usr/bin/env python3
"""
Тест создания небольшого ордера NOCK
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

def test_small_nock_order():
    """Тестируем создание небольшого ордера NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            create_sell_order_safetrade,
            get_all_markets
        )
        
        logging.info("🔧 Тестирование создания небольшого ордера NOCK...")
        
        # 1. Получаем информацию о рынке NOCK
        markets = get_all_markets()
        if not markets:
            logging.error("❌ Не удалось получить рынки")
            return False
        
        # Ищем информацию о рынке NOCK
        nock_market = None
        for market in markets:
            if market.get('id', '').lower() == 'nockusdt':
                nock_market = market
                break
        
        if not nock_market:
            logging.error("❌ Рынок NOCK/USDT не найден")
            return False
        
        logging.info(f"✅ Информация о рынке NOCK: {nock_market}")
        
        # 2. Пробуем создать небольшой лимитный ордер
        # Используем минимальную сумму из информации о рынке
        min_amount = float(nock_market.get('min_amount', 0.01))
        amount_precision = nock_market.get('amount_precision', 4)
        
        # Округляем до правильной точности
        formatted_amount = f"{min_amount:.{amount_precision}f}"
        rounded_amount = float(formatted_amount)
        
        logging.info(f"Пробуем создать лимитный ордер на {rounded_amount} NOCK по цене 0.001 USDT")
        
        # Создаем лимитный ордер с очень низкой ценой
        result = create_sell_order_safetrade(
            market_symbol="nockusdt",
            amount=rounded_amount,
            order_type="limit",
            price=0.001  # Очень низкая цена, чтобы ордер не исполнился сразу
        )
        
        if result and "✅" in result:
            logging.info(f"✅ Успешно создан ордер: {result}")
            return True
        else:
            logging.error(f"❌ Не удалось создать ордер: {result}")
            return False
            
    except Exception as e:
        logging.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск теста создания небольшого ордера NOCK...")
    success = test_small_nock_order()
    
    if success:
        print("✅ Тест пройден успешно!")
        sys.exit(0)
    else:
        print("❌ Тест не пройден!")
        sys.exit(1)