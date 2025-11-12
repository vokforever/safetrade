#!/usr/bin/env python3
"""
Тест создания небольшого рыночного ордера NOCK
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

def test_small_market_order():
    """Тестируем создание небольшого рыночного ордера NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            create_sell_order_safetrade,
            get_all_markets,
            get_ticker_price
        )
        
        logging.info("🧪 Тестирование создания небольшого рыночного ордера NOCK...")
        
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
        
        # 2. Получаем текущую цену
        price = get_ticker_price('nockusdt')
        if price:
            logging.info(f"✅ Текущая цена NOCK/USDT: {price}")
        else:
            logging.warning("❌ Не удалось получить цену NOCK/USDT")
            return False
        
        # 3. Рассчитываем минимальную сумму в USD
        min_amount_nock = float(nock_market.get('min_amount', 0.01))
        min_order_usd = min_amount_nock * price
        
        logging.info(f"✅ Минимальный размер ордера: {min_amount_nock} NOCK = ${min_order_usd:.6f}")
        
        # 4. Пробуем создать рыночный ордер с минимальной суммой
        # Используем немного большую сумму, чтобы быть уверенными, что она больше минимальной в USD
        test_amount = min_amount_nock * 2  # Удваиваем минимальную сумму
        
        logging.info(f"Пробуем создать рыночный ордер на {test_amount} NOCK")
        
        # Создаем рыночный ордер
        result = create_sell_order_safetrade(
            market_symbol="nockusdt",
            amount=test_amount,
            order_type="market"
        )
        
        if result and "✅" in result:
            logging.info(f"✅ Успешно создан рыночный ордер: {result}")
            return True
        else:
            logging.error(f"❌ Не удалось создать рыночный ордер: {result}")
            return False
            
    except Exception as e:
        logging.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск теста создания небольшого рыночного ордера NOCK...")
    success = test_small_market_order()
    
    if success:
        print("✅ Тест пройден успешно!")
        sys.exit(0)
    else:
        print("❌ Тест не пройден!")
        sys.exit(1)