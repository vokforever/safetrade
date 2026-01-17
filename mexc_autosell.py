"""
MEXC Auto-Sell Script (Dust Sweeper)
Продает все монеты на балансе в USDT по рынку.

Использование:
    python mexc_autosell.py

Переменные окружения:
    MEXC_ACCESSKEY - API ключ MEXC
    MEXC_SECRETKEY - API секрет MEXC
"""

import os
import time
import logging
from decimal import Decimal, ROUND_FLOOR, InvalidOperation
from dotenv import load_dotenv
from mexc_api.spot import Spot
from requests.exceptions import RequestException

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MexcSweeper:
    """Класс для автоматической продажи всех монет на балансе MEXC в USDT."""
    
    def __init__(self, api_key: str, api_secret: str):
        """
        Инициализация клиента MEXC и загрузка правил торговли.
        
        Args:
            api_key: API ключ MEXC
            api_secret: API секрет MEXC
        """
        self.client = Spot(api_key=api_key, api_secret=api_secret)
        self.symbol_rules = {}
        self.logger = logging.getLogger("MexcSweeper")
        
        # Загружаем правила обмена при инициализации
        self._load_exchange_info()
    
    def _load_exchange_info(self) -> None:
        """
        Кеширует правила торговли (stepSize, minNotional, minQty) для всех USDT пар.
        
        API MEXC очень строг к количеству знаков после запятой.
        Если отправить 10.12345678 при шаге 0.01, ордер вернет ошибку.
        """
        try:
            self.logger.info("Loading exchange info...")
            info = self.client.market.exchange_info()
            
            # В ответе exchange_info ищем список 'symbols'
            symbols = info.get('symbols', [])
            
            for symbol_data in symbols:
                symbol = symbol_data.get('symbol', '')
                
                # Отфильтровываем только USDT пары
                if not symbol.endswith('USDT'):
                    continue
                
                # Извлекаем правила торговли
                rules = {
                    'min_qty': Decimal('0.000001'),      # Минимальный размер ордера (по умолчанию)
                    'step_size': Decimal('0.000001'),    # Шаг лота (точность количества)
                    'min_notional': Decimal('5.0')       # Минимальная сумма сделки в USDT
                }
                
                # Пытаемся получить точность из baseAssetPrecision
                base_precision = symbol_data.get('baseAssetPrecision')
                if base_precision is not None:
                    # Если basePrecision - это число знаков после запятой (например, 8)
                    try:
                        precision = int(base_precision)
                        if precision >= 0:
                            # Создаем step_size на основе количества знаков
                            step_str = "0." + "0" * precision if precision > 0 else "1"
                            rules['step_size'] = Decimal(step_str)
                            rules['min_qty'] = Decimal(step_str)
                    except (ValueError, TypeError):
                        pass
                
                # Пытаемся найти фильтры LOT_SIZE и MIN_NOTIONAL
                filters = symbol_data.get('filters', [])
                for filter_item in filters:
                    filter_type = filter_item.get('filterType', '')
                    
                    if filter_type == 'LOT_SIZE':
                        # Шаг лота
                        step_size = filter_item.get('stepSize', '0.000001')
                        min_qty = filter_item.get('minQty', '0.000001')
                        try:
                            rules['step_size'] = Decimal(str(step_size))
                            rules['min_qty'] = Decimal(str(min_qty))
                        except InvalidOperation:
                            pass
                    
                    elif filter_type == 'MIN_NOTIONAL':
                        # Минимальная сумма сделки
                        min_notional = filter_item.get('minNotional', '5.0')
                        try:
                            rules['min_notional'] = Decimal(str(min_notional))
                        except InvalidOperation:
                            pass
                
                self.symbol_rules[symbol] = rules
            
            self.logger.info(f"Loaded rules for {len(self.symbol_rules)} USDT pairs")
            
        except Exception as e:
            self.logger.error(f"Error loading exchange info: {e}")
            raise
    
    def _round_step(self, quantity, step_size) -> Decimal:
        """
        Округляет количество под требования биржи в меньшую сторону.
        
        Args:
            quantity: Количество для округления
            step_size: Шаг лота (может быть int для количества знаков или Decimal для значения)
            
        Returns:
            Округленное количество как Decimal
        """
        try:
            q = Decimal(str(quantity))
            
            # Если step_size это число знаков (int), например 2:
            if isinstance(step_size, int) or (
                isinstance(step_size, Decimal) and 
                step_size >= 1 and 
                step_size % 1 == 0
            ):
                precision = int(step_size)
                if precision == 0:
                    return q.quantize(Decimal('1'), rounding=ROUND_FLOOR)
                else:
                    format_str = "1." + "0" * precision
                    return q.quantize(Decimal(format_str), rounding=ROUND_FLOOR)
            
            # Если step_size это float или Decimal, например 0.01:
            step = Decimal(str(step_size))
            return q.quantize(step, rounding=ROUND_FLOOR)
            
        except (InvalidOperation, ValueError) as e:
            self.logger.error(f"Error rounding quantity {quantity} with step {step_size}: {e}")
            return Decimal('0')
    
    def _get_current_price(self, symbol: str) -> Decimal:
        """
        Получает текущую цену для символа.
        
        Args:
            symbol: Торговая пара (например, "BTCUSDT")
            
        Returns:
            Текущая цена как Decimal
        """
        try:
            ticker = self.client.market.ticker_price(symbol=symbol)
            # ticker_price может вернуть как словарь, так и список
            if isinstance(ticker, list) and len(ticker) > 0:
                price = ticker[0].get('price', '0')
            elif isinstance(ticker, dict):
                price = ticker.get('price', '0')
            else:
                price = '0'
            return Decimal(str(price))
        except Exception as e:
            self.logger.warning(f"Error getting price for {symbol}: {e}")
            return Decimal('0')
    
    def _get_balances(self) -> list:
        """
        Получает список активов с положительным балансом (кроме USDT).
        
        Returns:
            Список словарей с информацией о балансе
        """
        try:
            self.logger.info("Fetching account balances...")
            account = self.client.account.get_account_info()
            
            # Получаем балансы
            balances = account.get('balances', [])
            
            # Фильтруем только те, где free > 0 и исключаем USDT
            active_balances = [
                b for b in balances 
                if float(b.get('free', '0')) > 0 and b.get('asset') != 'USDT'
            ]
            
            self.logger.info(f"Found {len(active_balances)} assets with positive balance")
            return active_balances
            
        except Exception as e:
            self.logger.error(f"Error fetching balances: {e}")
            return []
    
    def process_balances(self, dry_run: bool = False) -> dict:
        """
        Основной метод для обработки и продажи всех активов.
        
        Args:
            dry_run: Если True, только логирует действия без реальной продажи
            
        Returns:
            Словарь с результатами: {'sold': [], 'skipped': [], 'errors': []}
        """
        results = {
            'sold': [],
            'skipped': [],
            'errors': []
        }
        
        # Получаем балансы
        balances = self._get_balances()
        
        for asset_info in balances:
            asset = asset_info.get('asset')
            free_balance = Decimal(str(asset_info.get('free', '0')))
            
            # Составляем символ пары
            symbol = f"{asset}USDT"
            
            # Проверяем, торгуется ли такая пара
            if symbol not in self.symbol_rules:
                self.logger.warning(f"Pair {symbol} not found in exchange rules. Skipping.")
                results['skipped'].append({
                    'asset': asset,
                    'reason': f'Pair {symbol} not found or not trading'
                })
                continue
            
            # Получаем правила для этой пары
            rules = self.symbol_rules[symbol]
            step_size = rules['step_size']
            min_qty = rules['min_qty']
            min_notional = rules['min_notional']
            
            # Нормализуем количество
            formatted_qty = self._round_step(free_balance, step_size)
            
            # Проверяем минимальное количество
            if formatted_qty < min_qty:
                self.logger.info(
                    f"Skipping {asset}: quantity {formatted_qty} < min_qty {min_qty} (dust)"
                )
                results['skipped'].append({
                    'asset': asset,
                    'reason': f'Quantity {formatted_qty} < min_qty {min_qty}'
                })
                continue
            
            # Проверяем минимальную сумму сделки (получаем текущую цену)
            current_price = self._get_current_price(symbol)
            if current_price > 0:
                estimated_value = formatted_qty * current_price
                if estimated_value < min_notional:
                    self.logger.info(
                        f"Skipping {asset}: estimated value {estimated_value} USDT < min_notional {min_notional} USDT"
                    )
                    results['skipped'].append({
                        'asset': asset,
                        'reason': f'Estimated value {estimated_value} USDT < min_notional {min_notional} USDT'
                    })
                    continue
            
            # Продаем
            try:
                if dry_run:
                    self.logger.info(
                        f"[DRY RUN] Would sell {formatted_qty} {asset} for {symbol}"
                    )
                    results['sold'].append({
                        'asset': asset,
                        'quantity': str(formatted_qty),
                        'dry_run': True
                    })
                else:
                    self.logger.info(f"Selling {formatted_qty} {asset}...")
                    
                    # Отправляем рыночный ордер на продажу
                    order_response = self.client.account.new_order(
                        symbol=symbol,
                        side="SELL",
                        order_type="MARKET",
                        options={
                            "quantity": str(formatted_qty)
                        }
                    )
                    
                    self.logger.info(f"Successfully sold {asset}: {order_response}")
                    results['sold'].append({
                        'asset': asset,
                        'quantity': str(formatted_qty),
                        'response': order_response
                    })
                    
                    # Небольшая пауза между ордерами, чтобы не превысить rate limits
                    time.sleep(0.5)
                    
            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"Error selling {asset}: {error_msg}")
                results['errors'].append({
                    'asset': asset,
                    'error': error_msg
                })
                
                # Если это ошибка rate limit, делаем паузу
                if 'too many requests' in error_msg.lower() or 'rate limit' in error_msg.lower():
                    self.logger.info("Rate limit hit, waiting 2 seconds...")
                    time.sleep(2)
        
        return results
    
    def sweep(self, dry_run: bool = False) -> None:
        """
        Запускает процесс продажи всех активов.
        
        Args:
            dry_run: Если True, только логирует действия без реальной продажи
        """
        self.logger.info("=" * 50)
        self.logger.info("Starting MEXC Auto-Sell (Dust Sweeper)")
        if dry_run:
            self.logger.info("MODE: DRY RUN (no actual trades)")
        self.logger.info("=" * 50)
        
        results = self.process_balances(dry_run=dry_run)
        
        # Выводим итоговую статистику
        self.logger.info("=" * 50)
        self.logger.info("SUMMARY:")
        self.logger.info(f"  Sold: {len(results['sold'])} assets")
        self.logger.info(f"  Skipped: {len(results['skipped'])} assets")
        self.logger.info(f"  Errors: {len(results['errors'])} assets")
        
        if results['sold']:
            self.logger.info("\nSold assets:")
            for item in results['sold']:
                self.logger.info(f"  - {item['asset']}: {item['quantity']}")
        
        if results['skipped']:
            self.logger.info("\nSkipped assets:")
            for item in results['skipped']:
                self.logger.info(f"  - {item['asset']}: {item['reason']}")
        
        if results['errors']:
            self.logger.info("\nErrors:")
            for item in results['errors']:
                self.logger.info(f"  - {item['asset']}: {item['error']}")
        
        self.logger.info("=" * 50)


def main():
    """Точка входа для запуска скрипта."""
    # Получаем ключи из переменных окружения
    api_key = os.getenv('MEXC_ACCESSKEY')
    api_secret = os.getenv('MEXC_SECRETKEY')
    
    if not api_key or not api_secret:
        logger.error(
            "MEXC_ACCESSKEY and MEXC_SECRETKEY environment variables must be set"
        )
        return
    
    # Создаем экземпляр и запускаем
    try:
        sweeper = MexcSweeper(api_key=api_key, api_secret=api_secret)
        
        # Для тестирования можно использовать dry_run=True
        # sweeper.sweep(dry_run=True)
        
        # Реальная продажа
        sweeper.sweep(dry_run=False)
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")


if __name__ == "__main__":
    main()
