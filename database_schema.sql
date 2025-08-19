-- =====================================================
-- SafeTrade Trading Bot Database Schema
-- =====================================================
-- 
-- Этот файл содержит SQL скрипты для создания всех таблиц,
-- используемых SafeTrade Trading Bot
--
-- База данных: PostgreSQL/SQLite совместимый
-- 
-- =====================================================

-- Таблица для хранения исторических данных о ценах
CREATE TABLE IF NOT EXISTS safetrade_price_history (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price NUMERIC NOT NULL,
    volume NUMERIC,
    high NUMERIC,
    low NUMERIC,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для хранения истории ордеров
CREATE TABLE IF NOT EXISTS safetrade_order_history (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    price NUMERIC,
    total NUMERIC,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для хранения решений ИИ
CREATE TABLE IF NOT EXISTS safetrade_ai_decisions (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    decision_data TEXT NOT NULL,
    market_data TEXT,
    reasoning TEXT,
    confidence NUMERIC,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для хранения торговых пар
CREATE TABLE IF NOT EXISTS safetrade_trading_pairs (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_updated TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для метрик производительности
CREATE TABLE IF NOT EXISTS safetrade_performance_metrics (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value NUMERIC NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- Индексы для улучшения производительности
-- =====================================================

-- Индекс для быстрого поиска по символу и времени в истории цен
CREATE INDEX IF NOT EXISTS idx_safetrade_price_history_symbol_timestamp 
ON safetrade_price_history(symbol, timestamp);

-- Индекс для быстрого поиска по ID ордера
CREATE INDEX IF NOT EXISTS idx_safetrade_order_history_order_id 
ON safetrade_order_history(order_id);

-- Индекс для быстрого поиска по символу и времени в истории ордеров
CREATE INDEX IF NOT EXISTS idx_safetrade_order_history_symbol_timestamp 
ON safetrade_order_history(symbol, timestamp);

-- Индекс для быстрого поиска по типу решения и времени в решениях ИИ
CREATE INDEX IF NOT EXISTS idx_safetrade_ai_decisions_decision_type_timestamp 
ON safetrade_ai_decisions(decision_type, timestamp);

-- Индекс для быстрого поиска по символу торговой пары
CREATE INDEX IF NOT EXISTS idx_safetrade_trading_pairs_symbol 
ON safetrade_trading_pairs(symbol);

-- Индекс для быстрого поиска по базовой валюте
CREATE INDEX IF NOT EXISTS idx_safetrade_trading_pairs_base_currency 
ON safetrade_trading_pairs(base_currency);

-- Индекс для быстрого поиска по типу метрики и времени
CREATE INDEX IF NOT EXISTS idx_safetrade_performance_metrics_metric_type_timestamp 
ON safetrade_performance_metrics(metric_type, timestamp);

-- =====================================================
-- Комментарии к таблицам
-- =====================================================

/*
safetrade_price_history - хранит исторические данные о ценах криптовалют
- timestamp: время получения цены (TEXT для совместимости)
- symbol: символ торговой пары (например, BTCUSDT)
- price: текущая цена (NUMERIC для точности)
- volume: объем торгов (NUMERIC для точности)
- high: максимальная цена за период (NUMERIC для точности)
- low: минимальная цена за период (NUMERIC для точности)

safetrade_order_history - хранит историю всех торговых ордеров
- order_id: уникальный ID ордера с биржи
- timestamp: время создания ордера
- symbol: торговая пара
- side: сторона (buy/sell)
- order_type: тип ордера (market/limit/twap/iceberg/adaptive)
- amount: количество криптовалюты (NUMERIC для точности)
- price: цена (NUMERIC для точности, для лимитных ордеров)
- total: общая стоимость в USDT (NUMERIC для точности)
- status: статус ордера (pending/filled/cancelled)

safetrade_ai_decisions - хранит решения ИИ-помощника
- timestamp: время принятия решения
- decision_type: тип решения (trading_strategy)
- decision_data: JSON с параметрами решения
- market_data: JSON с рыночными данными
- reasoning: обоснование решения
- confidence: уверенность в решении (NUMERIC 0.0-1.0)

safetrade_trading_pairs - хранит доступные торговые пары
- symbol: символ пары
- base_currency: базовая валюта (BTC, ETH)
- quote_currency: котируемая валюта (USDT)
- is_active: активна ли пара (BOOLEAN)
- last_updated: время последнего обновления

safetrade_performance_metrics - хранит метрики производительности
- timestamp: время измерения
- metric_type: тип метрики
- metric_name: название метрики
- value: значение метрики (NUMERIC для точности)
- metadata: дополнительные данные в JSON

ПРИМЕЧАНИЕ: Схема совместима с PostgreSQL и SQLite
- SERIAL для автоинкремента (PostgreSQL)
- NUMERIC для точных числовых значений
- TIMESTAMP для временных меток
- BOOLEAN для логических значений
*/
