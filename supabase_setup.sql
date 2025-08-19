-- Supabase setup script for SafeTrade project
-- This script creates all required tables with the safetrade_ prefix

-- Enable UUID extension for primary keys
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table for storing historical price data
CREATE TABLE IF NOT EXISTS safetrade_price_history (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price NUMERIC NOT NULL,
    volume NUMERIC,
    high NUMERIC,
    low NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table for storing order history
CREATE TABLE IF NOT EXISTS safetrade_order_history (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    order_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    price NUMERIC,
    total NUMERIC,
    status TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table for storing AI decisions
CREATE TABLE IF NOT EXISTS safetrade_ai_decisions (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    timestamp TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    decision_data TEXT NOT NULL,
    market_data TEXT,
    reasoning TEXT,
    confidence NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table for storing trading pairs
CREATE TABLE IF NOT EXISTS safetrade_trading_pairs (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_updated TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table for storing performance metrics
CREATE TABLE IF NOT EXISTS safetrade_performance_metrics (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    timestamp TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value NUMERIC NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_safetrade_price_history_symbol_timestamp 
ON safetrade_price_history(symbol, timestamp);

CREATE INDEX IF NOT EXISTS idx_safetrade_order_history_order_id 
ON safetrade_order_history(order_id);

CREATE INDEX IF NOT EXISTS idx_safetrade_order_history_symbol_timestamp 
ON safetrade_order_history(symbol, timestamp);

CREATE INDEX IF NOT EXISTS idx_safetrade_ai_decisions_decision_type_timestamp 
ON safetrade_ai_decisions(decision_type, timestamp);

CREATE INDEX IF NOT EXISTS idx_safetrade_trading_pairs_symbol 
ON safetrade_trading_pairs(symbol);

CREATE INDEX IF NOT EXISTS idx_safetrade_trading_pairs_base_currency 
ON safetrade_trading_pairs(base_currency);

CREATE INDEX IF NOT EXISTS idx_safetrade_performance_metrics_metric_type_timestamp 
ON safetrade_performance_metrics(metric_type, timestamp);

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger for updated_at on order_history table
CREATE TRIGGER update_safetrade_order_history_updated_at 
    BEFORE UPDATE ON safetrade_order_history 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Grant necessary permissions (adjust as needed for your Supabase setup)
-- These are typically handled automatically by Supabase RLS policies
