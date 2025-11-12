#!/usr/bin/env python3
"""
Проверка информации о рынке NOCK
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

def check_nock_market():
    """Проверяем информацию о рынке NOCK"""
    try:
        # Импортируем основные функции из main.py
        from main import (
            get_all_markets,
            get_ticker_price,
            scraper,
            BASE_URL
        )
        
        logging.info("🔍 Проверка информации о рынке NOCK...")
        
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
        
        # 3. Пробуем получить детальную информацию о рынке
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
        
        # 4. Проверяем книгу ордеров
        try:
            url = f"{BASE_URL}/trade/public/order-book/nockusdt"
            response = scraper.get(url, timeout=30)
            if response.status_code == 200:
                orderbook = response.json()
                if orderbook.get('bids') and orderbook.get('asks'):
                    best_bid = float(orderbook['bids'][0][0])
                    best_ask = float(orderbook['asks'][0][0])
                    logging.info(f"✅ Лучший bid: {best_bid}, лучший ask: {best_ask}")
                    
                    # Проверяем минимальный размер ордера из книги ордеров
                    min_bid_amount = float(orderbook['bids'][0][1])
                    min_ask_amount = float(orderbook['asks'][0][1])
                    logging.info(f"✅ Минимальный объем bid: {min_bid_amount}, ask: {min_ask_amount}")
                else:
                    logging.warning("❌ Пустая книга ордеров")
            else:
                logging.warning(f"❌ Не удалось получить книгу ордеров: {response.status_code}")
        except Exception as e:
            logging.warning(f"❌ Ошибка при получении книги ордеров: {e}")
        
        return True
            
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке рынка: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Запуск проверки рынка NOCK...")
    success = check_nock_market()
    
    if success:
        print("✅ Проверка завершена успешно!")
        sys.exit(0)
    else:
        print("❌ Проверка не пройдена!")
        sys.exit(1)