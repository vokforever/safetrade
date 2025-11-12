#!/usr/bin/env python3
"""
Проверка минимального размера ордера для NOCK
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

def check_nock_min_order():
    """Проверяем минимальный размер ордера для NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            get_all_markets,
            get_ticker_price,
            scraper,
            BASE_URL
        )
        
        logging.info("🔍 Проверка минимального размера ордера для NOCK...")
        
        # 1. Получаем все рынки
        markets = get_all_markets()
        
        if not markets:
            logging.error("❌ Не удалось получить рынки")
            return False
        
        # Ищем рынок NOCK/USDT
        nock_market = None
        for market in markets:
            if market.get('id', '').lower() == 'nockusdt':
                nock_market = market
                break
        
        if not nock_market:
            logging.error("❌ Рынок NOCK/USDT не найден")
            return False
        
        logging.info(f"✅ Найден рынок NOCK/USDT: {nock_market}")
        
        # 2. Получаем текущую цену
        price = get_ticker_price('nockusdt')
        if price:
            logging.info(f"✅ Текущая цена NOCK/USDT: {price}")
        else:
            logging.warning("❌ Не удалось получить цену NOCK/USDT")
            return False
        
        # 3. Рассчитываем минимальный размер ордера в USD
        min_amount_nock = float(nock_market.get('min_amount', 0.01))
        min_order_usd = min_amount_nock * price
        
        logging.info(f"✅ Минимальный размер ордера: {min_amount_nock} NOCK = ${min_order_usd:.6f}")
        
        # 4. Проверяем, есть ли информация о минимальном размере ордера в USD
        try:
            url = f"{BASE_URL}/trade/public/markets/nockusdt"
            response = scraper.get(url, timeout=30)
            if response.status_code == 200:
                market_info = response.json()
                logging.info(f"✅ Детальная информация о рынке: {market_info}")
            else:
                logging.warning(f"❌ Не удалось получить детальную информацию: {response.status_code}")
        except Exception as e:
            logging.warning(f"❌ Ошибка при получении детальной информации: {e}")
        
        return True
            
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке минимального ордера: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск проверки минимального ордера NOCK...")
    success = check_nock_min_order()
    
    if success:
        print("✅ Проверка завершена успешно!")
        sys.exit(0)
    else:
        print("❌ Проверка не пройдена!")
        sys.exit(1)