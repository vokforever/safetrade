#!/usr/bin/env python3
"""
Скрипт для ежечасной автоматической продажи всех альткоинов
"""

import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

# Добавляем текущую директорию в путь для импорта модулей
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Настройка логирования
log_dir = Path("data")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "hourly_autosell.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def run_hourly_autosell():
    """Запускает ежечасную автопродажу"""
    try:
        from main import auto_sell_all_altcoins
        
        logging.info("🚀 Запуск ежечасной автопродажи...")
        logging.info(f"⏰ Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Запускаем автопродажу
        result = auto_sell_all_altcoins()
        
        if result["success"]:
            logging.info(f"✅ Автопродажа завершена успешно!")
            logging.info(f"   Обработано валют: {result['total_processed']}")
            logging.info(f"   Успешных продаж: {result['successful_sales']}")
            logging.info(f"   Неудачных попыток: {result['failed_sales']}")
            return True
        else:
            logging.error(f"❌ Автопродажа завершилась с ошибкой: {result['message']}")
            return False
            
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при запуске автопродажи: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Главная функция"""
    logging.info("=" * 60)
    logging.info("🤖 SafeTrade Ежечасная Автопродажа")
    logging.info("=" * 60)
    
    # Запускаем автопродажу
    success = run_hourly_autosell()
    
    if success:
        logging.info("✅ Ежечасная автопродажа завершена успешно")
        sys.exit(0)
    else:
        logging.error("❌ Ежечасная автопродажа завершилась с ошибкой")
        sys.exit(1)

if __name__ == "__main__":
    main()