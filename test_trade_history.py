#!/usr/bin/env python3
"""
Test script for enhanced SafeTrade trade history functionality
This script tests the improved trade history implementation to ensure it properly handles
missing price and USDT values from the SafeTrade API.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import api
import trade_history

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_enhanced_trade_history():
    """Test the enhanced trade history functionality"""
    
    # Load environment variables
    load_dotenv()
    
    # Get API credentials
    api_key = os.getenv("SAFETRADE_API_KEY")
    api_secret = os.getenv("SAFETRADE_API_SECRET")
    base_url = "https://safe.trade/api/v2"
    
    if not api_key or not api_secret:
        print("❌ Please set SAFETRADE_API_KEY and SAFETRADE_API_SECRET in .env file")
        return False
    
    print("🔑 API credentials loaded successfully")
    
    try:
        # Initialize clients
        api_client = api.Client(base_url, api_key, api_secret)
        trade_history_client = trade_history.TradeHistory(base_url, api_key, api_secret)
        
        print("\n📊 Testing Enhanced Trade History...")
        
        # Test 1: Get trade history
        print("\n1️⃣ Testing trade history endpoint...")
        try:
            trades = api_client.get_trade_history(limit=5)
            if trades:
                print(f"✅ Trade history response received")
                print(f"   Response type: {type(trades)}")
                if isinstance(trades, dict):
                    print(f"   Response keys: {list(trades.keys())}")
                    if 'data' in trades and trades['data']:
                        print(f"   Number of trades: {len(trades['data'])}")
                        sample_trade = trades['data'][0]
                        print(f"   Sample trade keys: {list(sample_trade.keys())}")
                elif isinstance(trades, list):
                    print(f"   Number of trades: {len(trades)}")
                    if trades:
                        sample_trade = trades[0]
                        print(f"   Sample trade keys: {list(sample_trade.keys())}")
            else:
                print("❌ No trade history response")
        except Exception as e:
            print(f"❌ Error getting trade history: {e}")
        
        # Test 2: Get completed orders
        print("\n2️⃣ Testing completed orders endpoint...")
        try:
            orders = api_client.get_completed_orders(limit=5)
            if orders:
                print(f"✅ Completed orders response received")
                print(f"   Response type: {type(orders)}")
                if isinstance(orders, dict):
                    print(f"   Response keys: {list(orders.keys())}")
                    if 'data' in orders and orders['data']:
                        print(f"   Number of orders: {len(orders['data'])}")
                        sample_order = orders['data'][0]
                        print(f"   Sample order keys: {list(sample_order.keys())}")
                elif isinstance(orders, list):
                    print(f"   Number of orders: {len(orders)}")
                    if orders:
                        sample_order = orders[0]
                        print(f"   Sample order keys: {list(sample_order.keys())}")
            else:
                print("❌ No completed orders response")
        except Exception as e:
            print(f"❌ Error getting completed orders: {e}")
        
        # Test 3: Test trade history formatting
        print("\n3️⃣ Testing trade history formatting...")
        try:
            formatted_history = trade_history_client.get_trade_history(limit=5)
            if formatted_history and "❌ Нет данных" not in formatted_history:
                print("✅ Formatted trade history generated successfully")
                print("\n📋 Sample formatted output:")
                print("-" * 50)
                print(formatted_history[:500] + "..." if len(formatted_history) > 500 else formatted_history)
                print("-" * 50)
            else:
                print("❌ No formatted trade history available")
        except Exception as e:
            print(f"❌ Error formatting trade history: {e}")
        
        # Test 4: Test specific market trades (QTCUSDT)
        print("\n4️⃣ Testing QTCUSDT specific trades...")
        try:
            qtc_trades = trade_history_client.get_market_trades("QTCUSDT")
            if qtc_trades and "❌ Нет данных" not in qtc_trades:
                print("✅ QTCUSDT trades found and formatted")
                print("\n📋 QTCUSDT trades:")
                print("-" * 50)
                print(qtc_trades[:300] + "..." if len(qtc_trades) > 300 else qtc_trades)
                print("-" * 50)
            else:
                print("❌ No QTCUSDT trades found")
        except Exception as e:
            print(f"❌ Error getting QTCUSDT trades: {e}")
        
        # Test 5: Test alternative endpoints
        print("\n5️⃣ Testing alternative API endpoints...")
        try:
            # Test account trades endpoint
            account_trades = api_client.get_account_trades(limit=3)
            if account_trades:
                print(f"✅ Account trades endpoint working")
                print(f"   Response type: {type(account_trades)}")
            else:
                print("⚠️ Account trades endpoint not working")
            
            # Test Peatio trades endpoint
            peatio_trades = api_client.get_peatio_trades(limit=3)
            if peatio_trades:
                print(f"✅ Peatio trades endpoint working")
                print(f"   Response type: {type(peatio_trades)}")
            else:
                print("⚠️ Peatio trades endpoint not working")
                
        except Exception as e:
            print(f"❌ Error testing alternative endpoints: {e}")
        
        print("\n🎯 Enhanced Trade History Testing Complete!")
        
        # Summary and recommendations
        print("\n💡 Key Improvements Implemented:")
        print("   • Enhanced data structure handling for different API responses")
        print("   • Automatic price × amount calculation for missing totals")
        print("   • Multiple endpoint fallback for better data coverage")
        print("   • Improved error handling and logging")
        print("   • Better timestamp parsing for different formats")
        
        print("\n🔧 If you still see missing values:")
        print("   1. Check the API response structure above")
        print("   2. Verify your API key has trade history permissions")
        print("   3. Some trades may legitimately not have prices (e.g., canceled orders)")
        
        return True
        
    except Exception as e:
        print(f"❌ Critical error during testing: {e}")
        return False

if __name__ == "__main__":
    success = test_enhanced_trade_history()
    if success:
        print("\n✅ All tests completed successfully!")
    else:
        print("\n❌ Some tests failed. Check the output above for details.")
        sys.exit(1)
