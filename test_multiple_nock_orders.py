#!/usr/bin/env python3
"""
Тест создания нескольких ордеров NOCK
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

def test_multiple_nock_orders():
    """Тестируем создание нескольких ордеров NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            create_sell_order_safetrade,
            get_all_markets,
            get_ticker_price,
            get_sellable_balances
        )
        
        logging.info("🧪 Тестирование создания нескольких ордеров NOCK...")
        
        # 1. Получаем баланс NOCK
        balances = get_sellable_balances()
        if not balances or 'NOCK' not in balances:
            logging.error("❌ Не удалось получить баланс NOCK")
            return False
        
        nock_balance = balances['NOCK']
        logging.info(f"✅ Текущий баланс NOCK: {nock_balance}")
        
        # 2. Получаем информацию о рынке NOCK
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
        
        # 3. Получаем текущую цену
        price = get_ticker_price('nockusdt')
        if not price:
            logging.error("❌ Не удалось получить цену NOCK/USDT")
            return False
        
        logging.info(f"✅ Текущая цена NOCK/USDT: {price}")
        
        # 4. Рассчитываем количество ордеров
        # Пробуем создать 5 ордеров по равным частям
        order_count = 5
        amount_per_order = nock_balance / order_count
        
        logging.info(f"✅ Создаем {order_count} ордеров по {amount_per_order:.4f} NOCK каждый")
        
        # 5. Создаем ордера
        successful_orders = 0
        remaining_balance = nock_balance
        
        for i in range(order_count):
            if remaining_balance <= 0:
                logging.info(f"✅ Все средства проданы")
                break
            
            # Рассчитываем сумму для текущего ордера
            current_amount = min(amount_per_order, remaining_balance)
            
            # Округляем до правильной точности
            amount_precision = nock_market.get('amount_precision', 4)
            formatted_amount = f"{current_amount:.{amount_precision}f}"
            rounded_amount = float(formatted_amount)
            
            # Проверяем минимальный размер ордера в USD
            min_amount = float(nock_market.get('min_amount', 0.01))
            min_order_usd = min_amount * price
            order_usd = rounded_amount * price
            
            if order_usd < min_order_usd:
                logging.warning(f"Сумма ордера ${order_usd:.6f} меньше минимальной ${min_order_usd:.6f}")
                # Используем минимальную сумму
                rounded_amount = min_amount
                order_usd = min_order_usd
            
            logging.info(f"Создаем ордер {i+1}/{order_count}: {rounded_amount:.4f} NOCK (${order_usd:.6f})")
            
            # Создаем ордер
            result = create_sell_order_safetrade(
                market_symbol="nockusdt",
                amount=rounded_amount,
                order_type="market"
            )
            
            if result and "✅" in result:
                logging.info(f"✅ Ордер {i+1} успешно создан")
                successful_orders += 1
                remaining_balance -= rounded_amount
            else:
                logging.error(f"❌ Не удалось создать ордер {i+1}: {result}")
                # Если не удалось создать ордер, пробуем уменьшить сумму
                remaining_balance -= rounded_amount  # Все равно вычитаем, чтобы избежать бесконечного цикла
        
        logging.info(f"✅ Успешно создано {successful_orders} из {order_count} ордеров")
        logging.info(f"✅ Остаток баланса: {remaining_balance:.4f} NOCK")
        
        return successful_orders > 0
            
    except Exception as e:
        logging.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск теста создания нескольких ордеров NOCK...")
    success = test_multiple_nock_orders()
    
    if success:
        print("✅ Тест пройден успешно!")
        sys.exit(0)
    else:
        print("❌ Тест не пройден!")
        sys.exit(1)