#!/usr/bin/env python3
"""
Тестовый скрипт для проверки автопродажи NOCK
"""

import os
import sys
import logging
from dotenv import load_dotenv
import yaml
from pathlib import Path

# Загружаем переменные окружения
load_dotenv()

# Настройки логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_config():
    """Проверяем конфигурацию"""
    logging.info("🔍 Проверка конфигурации...")
    
    # Загружаем конфигурацию
    config_path = Path("config.yml")
    if not config_path.exists():
        logging.error("❌ Файл config.yml не найден")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        allowed_currencies = config.get('trading', {}).get('allowed_currencies', [])
        excluded_currencies = config.get('trading', {}).get('excluded_currencies', [])
        
        logging.info(f"✅ Разрешенные валюты: {allowed_currencies}")
        logging.info(f"✅ Исключенные валюты: {excluded_currencies}")
        
        if 'NOCK' in allowed_currencies:
            logging.info("✅ NOCK добавлен в список разрешенных валют")
            return True
        else:
            logging.error("❌ NOCK не найден в списке разрешенных валют")
            return False
            
    except Exception as e:
        logging.error(f"❌ Ошибка загрузки конфигурации: {e}")
        return False

def test_environment():
    """Проверяем переменные окружения"""
    logging.info("🔍 Проверка переменных окружения...")
    
    required_vars = ['SAFETRADE_API_KEY', 'SAFETRADE_API_SECRET', 'SUPABASE_URL', 'SUPABASE_KEY']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logging.error(f"❌ Отсутствуют переменные: {missing_vars}")
        return False
    
    logging.info("✅ Все обязательные переменные окружения настроены")
    return True

def test_supabase_connection():
    """Проверяем соединение с Supabase"""
    logging.info("🔍 Проверка соединения с Supabase...")
    
    try:
        from supabase import create_client
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        
        if not supabase_url or not supabase_key:
            logging.error("❌ Отсутствуют настройки Supabase")
            return False
        
        supabase = create_client(supabase_url, supabase_key)
        
        # Проверяем доступность таблиц
        result = supabase.table('safetrade_order_history').select('symbol').limit(1).execute()
        logging.info("✅ Соединение с Supabase установлено")
        logging.info("✅ Таблица safetrade_order_history доступна")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка соединения с Supabase: {e}")
        return False

def test_nock_trading_pair():
    """Проверяем наличие торговой пары NOCK/USDT"""
    logging.info("🔍 Проверка торговой пары NOCK/USDT...")
    
    try:
        # Импортируем функции из main.py
        sys.path.append('.')
        from main import get_all_markets, ALLOWED_CURRENCIES
        
        markets = get_all_markets()
        if not markets:
            logging.warning("⚠️ Не удалось получить торговые пары")
            return False
        
        # Ищем NOCK/USDT
        knock_usdt_found = False
        for market in markets:
            symbol = market.get('id', '').upper()
            base_unit = market.get('base_unit', '').upper()
            quote_unit = market.get('quote_unit', '').upper()
            
            if symbol == 'NOCKUSDT' or (base_unit == 'NOCK' and quote_unit == 'USDT'):
                knock_usdt_found = True
                logging.info(f"✅ Найдена торговая пара: {symbol}")
                break
        
        if not knock_usdt_found:
            logging.warning("⚠️ Торговая пара NOCK/USDT не найдена")
            return False
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка проверки торговой пары: {e}")
        return False

def test_autosell_logic():
    """Проверяем логику автопродажи"""
    logging.info("🔍 Проверка логики автопродажи...")
    
    try:
        sys.path.append('.')
        from main import get_sellable_balances, prioritize_sales
        
        # Проверяем получение балансов
        balances = get_sellable_balances()
        if balances is None:
            logging.warning("⚠️ Не удалось получить балансы")
            return False
        
        logging.info(f"✅ Получены балансы: {list(balances.keys())}")
        
        # Проверяем приоритизацию
        if balances:
            priority_scores = prioritize_sales(balances)
            logging.info(f"✅ Приоритизация работает, обработано {len(priority_scores)} валют")
            
            # Проверяем наличие NOCK в приоритезации
            knock_found = any(score.currency == 'NOCK' for score in priority_scores)
            if knock_found:
                logging.info("✅ NOCK найден в приоритезации")
            else:
                logging.info("ℹ️ NOCK не найден в текущих балансах")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка проверки логики автопродажи: {e}")
        return False

def main():
    """Главная функция тестирования"""
    logging.info("🚀 Запуск тестирования автопродажи NOCK")
    
    tests = [
        ("Конфигурация", test_config),
        ("Переменные окружения", test_environment),
        ("Соединение с Supabase", test_supabase_connection),
        ("Торговая пара NOCK/USDT", test_nock_trading_pair),
        ("Логика автопродажи", test_autosell_logic)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        logging.info(f"\n📋 Тест: {test_name}")
        try:
            if test_func():
                passed += 1
                logging.info(f"✅ Тест '{test_name}' пройден")
            else:
                logging.error(f"❌ Тест '{test_name}' не пройден")
        except Exception as e:
            logging.error(f"❌ Ошибка в тесте '{test_name}': {e}")
    
    logging.info(f"\n📊 Результаты тестирования: {passed}/{total} тестов пройдено")
    
    if passed == total:
        logging.info("🎉 Все тесты пройдены! Автопродажа NOCK готова к работе.")
        return True
    else:
        logging.warning("⚠️ Некоторые тесты не пройдены. Проверьте настройки.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)