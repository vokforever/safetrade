#!/usr/bin/env python3
"""
Проверка активных ордеров NOCK
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

def check_nock_orders():
    """Проверяем активные ордера NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            api_client
        )
        
        logging.info("🔍 Проверка активных ордеров NOCK...")
        
        # Получаем все ордера
        orders = api_client.get_orders()
        
        if not orders:
            logging.error("❌ Не удалось получить ордера")
            return False
        
        logging.info(f"✅ Получено {len(orders)} ордеров")
        
        # Ищем ордера с NOCK
        nock_orders = []
        total_nock_in_orders = 0
        
        for order in orders:
            market = order.get('market', '').lower()
            if 'nock' in market:
                nock_orders.append(order)
                
                # Суммируем количество NOCK в ордерах
                amount = order.get('amount')
                if amount:
                    try:
                        total_nock_in_orders += float(amount)
                    except (ValueError, TypeError):
                        pass
        
        if nock_orders:
            logging.info(f"✅ Найдено {len(nock_orders)} ордеров с NOCK:")
            for order in nock_orders:
                logging.info(f"   • ID: {order.get('id')}, Состояние: {order.get('state')}, Сторона: {order.get('side')}, Количество: {order.get('amount')}, Цена: {order.get('price')}")
            
            logging.info(f"✅ Общее количество NOCK в ордерах: {total_nock_in_orders}")
            
            # Получаем текущий баланс NOCK
            from main import get_sellable_balances
            balances = get_sellable_balances()
            nock_balance = balances.get('NOCK', 0) if balances else 0
            
            logging.info(f"✅ Текущий баланс NOCK: {nock_balance}")
            
            # Рассчитываем доступный баланс
            available_balance = nock_balance - total_nock_in_orders
            logging.info(f"✅ Доступный баланс NOCK: {available_balance}")
            
            if available_balance <= 0:
                logging.warning(f"❌ Доступный баланс NOCK ({available_balance}) меньше или равен 0")
                return False
        else:
            logging.info("✅ Активных ордеров с NOCK не найдено")
        
        return True
            
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке ордеров: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск проверки ордеров NOCK...")
    success = check_nock_orders()
    
    if success:
        print("✅ Проверка завершена успешно!")
        sys.exit(0)
    else:
        print("❌ Проверка не пройдена!")
        sys.exit(1)