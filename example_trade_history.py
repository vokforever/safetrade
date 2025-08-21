#!/usr/bin/env python3
"""
SafeTrade Enhanced Trade History Example
This file demonstrates how to use the enhanced API client to get proper trade history
with price and USDT values.
"""

import api
import trade_history
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    # Get API credentials from environment
    api_key = os.getenv("SAFETRADE_API_KEY")
    api_secret = os.getenv("SAFETRADE_API_SECRET")
    base_url = "https://safe.trade/api/v2"
    
    if not api_key or not api_secret:
        print("❌ Please set SAFETRADE_API_KEY and SAFETRADE_API_SECRET in .env file")
        return
    
    print("🔑 API credentials loaded successfully")
    
    # Initialize the enhanced API client
    client = api.Client(base_url, api_key, api_secret)
    trade_history_client = trade_history.TradeHistory(base_url, api_key, api_secret)
    
    print("\n📊 Testing Enhanced API Endpoints...")
    
    # Test 1: Get completed orders
    print("\n1️⃣ Testing completed orders endpoint...")
    try:
        completed_orders = client.get_completed_orders(limit=10)
        if completed_orders and completed_orders.get('data'):
            print(f"✅ Found {len(completed_orders['data'])} completed orders")
            # Show sample data structure
            if completed_orders['data']:
                sample = completed_orders['data'][0]
                print(f"   Sample order structure: {list(sample.keys())}")
        else:
            print("❌ No completed orders found or endpoint not working")
    except Exception as e:
        print(f"❌ Error getting completed orders: {e}")
    
    # Test 2: Get trade history
    print("\n2️⃣ Testing trade history endpoint...")
    try:
        trades = client.get_trade_history(limit=10)
        if trades and trades.get('data'):
            print(f"✅ Found {len(trades['data'])} trades")
            # Show sample data structure
            if trades['data']:
                sample = trades['data'][0]
                print(f"   Sample trade structure: {list(sample.keys())}")
        else:
            print("❌ No trades found or endpoint not working")
    except Exception as e:
        print(f"❌ Error getting trade history: {e}")
    
    # Test 3: Get specific market trades (QTCUSDT)
    print("\n3️⃣ Testing QTCUSDT specific trades...")
    try:
        qtc_trades = trade_history_client.get_market_trades("QTCUSDT")
        if qtc_trades and "❌ Нет данных" not in qtc_trades:
            print("✅ QTCUSDT trades found")
            print(qtc_trades[:200] + "..." if len(qtc_trades) > 200 else qtc_trades)
        else:
            print("❌ No QTCUSDT trades found")
    except Exception as e:
        print(f"❌ Error getting QTCUSDT trades: {e}")
    
    # Test 4: Get general trade history with formatting
    print("\n4️⃣ Testing formatted trade history...")
    try:
        formatted_history = trade_history_client.get_trade_history(limit=5)
        if formatted_history and "❌ Нет данных" not in formatted_history:
            print("✅ Formatted trade history:")
            print(formatted_history)
        else:
            print("❌ No formatted trade history available")
    except Exception as e:
        print(f"❌ Error getting formatted history: {e}")
    
    # Test 5: Test order details endpoint
    print("\n5️⃣ Testing order details endpoint...")
    try:
        # First get some orders to test with
        orders = client.get_orders(limit=1)
        if orders and orders.get('data'):
            order_id = orders['data'][0].get('id')
            if order_id:
                order_details = client.get_order_details(order_id)
                if order_details:
                    print(f"✅ Order details retrieved for order {order_id}")
                    print(f"   Order structure: {list(order_details.keys())}")
                else:
                    print(f"❌ Could not get details for order {order_id}")
            else:
                print("❌ No order ID found in response")
        else:
            print("❌ No orders available for testing order details")
    except Exception as e:
        print(f"❌ Error testing order details: {e}")
    
    print("\n🎯 API Testing Complete!")
    print("\n💡 If you're still seeing missing price/USDT values, it might be because:")
    print("   • The API endpoints return different data structures")
    print("   • Some trades don't have execution prices (e.g., canceled orders)")
    print("   • The API requires different authentication or parameters")
    
    print("\n🔧 To debug further:")
    print("   1. Check the actual API responses above")
    print("   2. Verify your API key has the right permissions")
    print("   3. Check if the SafeTrade API structure has changed")

if __name__ == "__main__":
    main()
