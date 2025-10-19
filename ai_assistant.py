import logging
import json
import time
from collections import deque
from threading import Lock
from typing import Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime

try:
    from cerebras.cloud.sdk import Cerebras
    CEREBRAS_AVAILABLE = True
except ImportError:
    CEREBRAS_AVAILABLE = False
    logging.warning("Библиотека Cerebras SDK не найдена. Функции ИИ будут отключены.")

# Классы, перенесенные из основного файла
class SellStrategy(Enum):
    MARKET = "market"
    LIMIT = "limit"
    TWAP = "twap"
    ICEBERG = "iceberg"
    ADAPTIVE = "adaptive"

@dataclass
class MarketData:
    symbol: str
    current_price: float
    volatility: float
    volume_24h: float
    bid_depth: float
    ask_depth: float
    spread: float
    
    def to_dict(self):
        return asdict(self)

@dataclass
class TradingDecision:
    strategy: SellStrategy
    parameters: Dict[str, Any]
    reasoning: str
    confidence: float

# Улучшенный Rate Limiter для Cerebras
class RateLimiter:
    def __init__(self, requests_per_min=30, tokens_per_min=60000):
        self.requests_per_min = requests_per_min
        self.tokens_per_min = tokens_per_min
        self.request_times = deque()
        self.token_usage = deque()
        self.lock = Lock()
    
    def can_make_request(self, estimated_tokens=1000):
        with self.lock:
            now = time.time()
            minute_ago = now - 60
            
            # Очищаем старые записи
            while self.request_times and self.request_times[0] < minute_ago:
                self.request_times.popleft()
            
            while self.token_usage and self.token_usage[0][0] < minute_ago:
                self.token_usage.popleft()
            
            # Проверяем лимиты
            current_requests = len(self.request_times)
            current_tokens = sum(usage[1] for usage in self.token_usage)
            
            return (current_requests < self.requests_per_min and 
                    current_tokens + estimated_tokens < self.tokens_per_min)
    
    def record_usage(self, tokens_used):
        with self.lock:
            now = time.time()
            self.request_times.append(now)
            self.token_usage.append((now, tokens_used))

# Глобальные переменные для ИИ
cerebras_client = None
cerebras_limiter = RateLimiter()
CEREBRAS_MODEL = "qwen-3-235b-a22b-thinking-2507"

def initialize_ai(api_key):
    """Инициализация клиента Cerebras."""
    global cerebras_client
    if api_key and CEREBRAS_AVAILABLE:
        try:
            cerebras_client = Cerebras(api_key=api_key)
            logging.info("Cerebras AI подключен")
            return True
        except Exception as e:
            logging.error(f"Ошибка инициализации Cerebras AI: {e}. Функции ИИ будут отключены.")
            cerebras_client = None
    return False

def get_ai_trading_decision(currency, balance, market_data, db_manager):
    """Получение решения о торговле от ИИ для конкретной валюты."""
    if not cerebras_client:
        return None
    
    estimated_tokens = 2000
    if not cerebras_limiter.can_make_request(estimated_tokens):
        logging.warning("Достигнут лимит Cerebras API. Используется стандартная стратегия.")
        return None
    
    try:
        # Валидация входных данных
        if balance <= 0 or not market_data:
            logging.warning(f"Некорректные данные для ИИ: balance={balance}, market_data={market_data}")
            return None
        
        # Определяем размер позиции в USD
        usd_value = balance * market_data.current_price
        
        # Выбираем базовую стратегию на основе размера позиции
        if usd_value < 50:
            base_strategy = "market"
        elif usd_value < 500:
            base_strategy = "limit"
        else:
            base_strategy = "twap"
        
        # Формируем контекст для ИИ
        context = f"""
        Ты - торговый ИИ-ассистент для криптовалютной биржи SafeTrade. Твоя задача - проанализировать текущие рыночные условия и предложить оптимальную стратегию для продажи {balance} {currency} за USDT.
        
        Текущие рыночные данные:
        - Баланс {currency}: {balance}
        - Стоимость в USD: ${usd_value:.2f}
        - Текущая цена: {market_data.current_price}
        - Волатильность рынка: {market_data.volatility:.4f}
        - Объем торгов за 24 часа: {market_data.volume_24h}
        - Глубина книги ордеров (покупка): {market_data.bid_depth}
        - Глубина книги ордеров (продажа): {market_data.ask_depth}
        - Спред: {market_data.spread:.4f}
        
        Рекомендуемая базовая стратегия: {base_strategy}
        
        Доступные стратегии:
        1. market - немедленное исполнение по рыночной цене
        2. limit - исполнение по указанной цене или лучше
        3. twap - разделение на части через равные промежутки времени
        4. iceberg - отображение только части ордера
        5. adaptive - динамический выбор на основе рыночных условий
        
        Ответь в формате JSON:
        {{
            "strategy": "market|limit|twap|iceberg|adaptive",
            "parameters": {{
                "price": 0.0,
                "duration_minutes": 60,
                "chunks": 6,
                "visible_amount": 0.1,
                "max_attempts": 20
            }},
            "reasoning": "Обоснование выбора стратегии",
            "confidence": 0.85
        }}
        """
        
        # Отправляем запрос к ИИ
        response = cerebras_client.chat.completions.create(
            messages=[{"role": "user", "content": context}],
            model=CEREBRAS_MODEL,
            max_completion_tokens=4000,
        )
        
        # Парсим ответ
        ai_response = response.choices[0].message.content
        
        # Ищем JSON в ответе
        try:
            start_idx = ai_response.find('{')
            end_idx = ai_response.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                json_str = ai_response[start_idx:end_idx]
                decision = json.loads(json_str)
                
                # Создаем объект решения
                trading_decision = TradingDecision(
                    strategy=SellStrategy(decision.get("strategy", "market")),
                    parameters=decision.get("parameters", {}),
                    reasoning=decision.get("reasoning", ""),
                    confidence=decision.get("confidence", 0.5)
                )
                
                # Сохраняем решение ИИ
                if db_manager:
                    db_manager.insert_ai_decision(
                        timestamp=datetime.now().isoformat(),
                        decision_type="trading_strategy",
                        decision_data=json.dumps(decision),
                        market_data=json.dumps(market_data.to_dict()),
                        reasoning=trading_decision.reasoning,
                        confidence=trading_decision.confidence
                    )
                
                # Обновляем использование rate limiter
                input_tokens = len(context) // 4
                output_tokens = len(ai_response) // 4
                cerebras_limiter.record_usage(input_tokens + output_tokens)
                
                return trading_decision
            else:
                logging.error(f"Не удалось найти JSON в ответе ИИ: {ai_response}")
                return None
        except (json.JSONDecodeError, ValueError) as e:
            logging.error(f"Ошибка парсинга JSON из ответа ИИ: {e}")
            return None
    except Exception as e:
        logging.error(f"Ошибка при получении решения от ИИ: {e}")
        return None