"""
Тестовый скрипт для проверки mexc_autosell.py в режиме dry_run.
"""

import os
from dotenv import load_dotenv
from mexc_autosell import MexcSweeper

# Загружаем переменные окружения из .env файла
load_dotenv()

# Получаем ключи из переменных окружения
api_key = os.getenv('MEXC_ACCESSKEY')
api_secret = os.getenv('MEXC_SECRETKEY')

if not api_key or not api_secret:
    print("ERROR: MEXC_ACCESSKEY and MEXC_SECRETKEY environment variables must be set")
    exit(1)

# Создаем экземпляр и запускаем в режиме dry_run
try:
    print("Testing MEXC Auto-Sell in DRY RUN mode...")
    print("=" * 50)
    
    sweeper = MexcSweeper(api_key=api_key, api_secret=api_secret)
    sweeper.sweep(dry_run=True)
    
    print("=" * 50)
    print("Test completed successfully!")
    
except Exception as e:
    print(f"Error during test: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
