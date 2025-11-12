#!/usr/bin/env python3
"""
Проверка детального баланса NOCK
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

def check_nock_balance():
    """Проверяем детальный баланс NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            api_client,
            get_all_balances
        )
        
        logging.info("🔍 Проверка детального баланса NOCK...")
        
        # 1. Получаем все балансы (включая нулевые)
        all_balances = get_all_balances()
        
        if not all_balances:
            logging.error("❌ Не удалось получить балансы")
            return False
        
        # Ищем баланс NOCK
        nock_balance = None
        logging.info(f"Структура all_balances: {type(all_balances)}")
        if isinstance(all_balances, dict):
            # Если балансы в формате словаря
            nock_balance = all_balances.get('NOCK')
            if nock_balance:
                logging.info(f"✅ Найден баланс NOCK в словаре: {nock_balance}")
        elif isinstance(all_balances, list):
            # Если балансы в формате списка
            for balance in all_balances:
                # balance может быть строкой или словарем
                if isinstance(balance, dict):
                    currency = balance.get('currency', '').upper()
                else:
                    continue
                    
                if currency == 'NOCK':
                    nock_balance = balance
                    break
        else:
            logging.warning(f"Неизвестный формат балансов: {type(all_balances)}")
        
        if not nock_balance:
            logging.error("❌ NOCK не найден в балансах")
            return False
        
        logging.info(f"✅ Детальный баланс NOCK: {nock_balance}")
        
        # 2. Проверяем активные ордера
        try:
            orders = api_client.get_orders()
            if orders:
                logging.info(f"✅ Получено {len(orders)} ордеров")
                
                # Ищем ордера с NOCK
                nock_orders = []
                for order in orders:
                    if 'nock' in order.get('market', '').lower():
                        nock_orders.append(order)
                
                if nock_orders:
                    logging.info(f"✅ Найдено {len(nock_orders)} ордеров с NOCK:")
                    for order in nock_orders:
                        logging.info(f"   • ID: {order.get('id')}, Состояние: {order.get('state')}, Сторона: {order.get('side')}, Количество: {order.get('amount')}, Цена: {order.get('price')}")
                else:
                    logging.info("✅ Активных ордеров с NOCK не найдено")
            else:
                logging.warning("❌ Не удалось получить ордера")
        except Exception as e:
            logging.warning(f"❌ Ошибка при получении ордеров: {e}")
        
        # 3. Пробуем получить детальную информацию о счете
        try:
            account_info = api_client.get("/account")
            if account_info:
                logging.info(f"✅ Информация о счете: {account_info}")
            else:
                logging.warning("❌ Не удалось получить информацию о счете")
        except Exception as e:
            logging.warning(f"❌ Ошибка при получении информации о счете: {e}")
        
        return True
            
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке баланса: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск проверки баланса NOCK...")
    success = check_nock_balance()
    
    if success:
        print("✅ Проверка завершена успешно!")
        sys.exit(0)
    else:
        print("❌ Проверка не пройдена!")
        sys.exit(1)