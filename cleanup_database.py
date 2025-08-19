#!/usr/bin/env python3
"""
Скрипт для очистки дублирующихся записей в базе данных SafeTrade
Используйте этот скрипт для решения проблем с дублирующимися торговыми парами
"""

import os
import sys
import logging
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def cleanup_database():
    """Очистка дублирующихся записей в базе данных"""
    
    # Загружаем переменные окружения
    load_dotenv()
    
    # Получаем настройки Supabase
    supabase_url = os.getenv('SAFETRADE_SUPABASE_URL')
    supabase_key = os.getenv('SAFETRADE_SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        logging.error("Не указаны переменные окружения SAFETRADE_SUPABASE_URL и SAFETRADE_SUPABASE_KEY")
        return False
    
    try:
        # Создаем клиент Supabase
        supabase: Client = create_client(supabase_url, supabase_key)
        logging.info("Подключение к Supabase установлено")
        
        # Получаем текущее состояние таблицы
        result = supabase.table('safetrade_trading_pairs').select('*').execute()
        
        if not result.data:
            logging.info("Таблица safetrade_trading_pairs пуста")
            return True
        
        total_records = len(result.data)
        logging.info(f"Всего записей в таблице: {total_records}")
        
        # Подсчитываем дубликаты
        symbols = [row['symbol'] for row in result.data]
        unique_symbols = set(symbols)
        duplicate_count = total_records - len(unique_symbols)
        
        logging.info(f"Уникальных символов: {len(unique_symbols)}")
        logging.info(f"Дублирующихся записей: {duplicate_count}")
        
        if duplicate_count == 0:
            logging.info("Дублирующихся записей не обнаружено")
            return True
        
        # Создаем словарь уникальных записей
        unique_records = {}
        for record in result.data:
            symbol = record['symbol']
            if symbol not in unique_records:
                unique_records[symbol] = record
        
        logging.info(f"Будет сохранено {len(unique_records)} уникальных записей")
        
        # Запрашиваем подтверждение
        response = input(f"Удалить {duplicate_count} дублирующихся записей? (y/N): ")
        if response.lower() != 'y':
            logging.info("Операция отменена пользователем")
            return False
        
        # Очищаем таблицу
        logging.info("Очистка таблицы...")
        supabase.table('safetrade_trading_pairs').delete().neq('id', '').execute()
        
        # Вставляем уникальные записи
        logging.info("Восстановление уникальных записей...")
        for record in unique_records.values():
            # Убираем id и created_at для создания новых
            record_copy = record.copy()
            if 'id' in record_copy:
                del record_copy['id']
            if 'created_at' in record_copy:
                del record_copy['created_at']
            
            supabase.table('safetrade_trading_pairs').insert(record_copy).execute()
        
        # Проверяем результат
        final_result = supabase.table('safetrade_trading_pairs').select('*').execute()
        logging.info(f"Очистка завершена. В таблице осталось {len(final_result.data)} записей")
        
        return True
        
    except Exception as e:
        logging.error(f"Ошибка при очистке базы данных: {e}")
        return False

def main():
    """Основная функция"""
    print("=" * 60)
    print("SafeTrade Database Cleanup Tool")
    print("=" * 60)
    
    if cleanup_database():
        print("\n✅ Очистка базы данных завершена успешно!")
    else:
        print("\n❌ Очистка базы данных завершилась с ошибкой!")
        sys.exit(1)

if __name__ == "__main__":
    main()
