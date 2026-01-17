"""
Test actual NOCK order with corrected floor rounding
"""
import os
import time
import hmac
import hashlib
import binascii
import cloudscraper
import json
import math
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SAFETRADE_API_KEY")
API_SECRET = os.getenv("SAFETRADE_API_SECRET")
BASE_URL = "https://safe.trade/api/v2"

def generate_signature(nonce, secret, key):
    hash_obj = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    hash_obj.update((nonce + key).encode())
    signature = hash_obj.digest()
    signature_hex = binascii.hexlify(signature).decode()
    return signature_hex

def get_auth_headers():
    nonce = str(int(time.time() * 1000))
    signature = generate_signature(nonce, API_SECRET, API_KEY)
    return {
        'X-Auth-Apikey': API_KEY,
        'X-Auth-Nonce': nonce,
        'X-Auth-Signature': signature,
        'Content-Type': 'application/json;charset=utf-8'
    }

def test_nock_order_with_floor_rounding():
    """Test creating a NOCK order with floor rounding"""
    scraper = cloudscraper.create_scraper()
    
    # Current NOCK balance (updated!)
    balance = 174.80966849
    precision = 4
    
    # Apply floor rounding (NEW METHOD)
    rounded_amount = math.floor(balance * 10**precision) / 10**precision
    
    print("=" * 60)
    print("ТЕСТ СОЗДАНИЯ ОРДЕРА С FLOOR ROUNDING")
    print("=" * 60)
    print(f"Баланс NOCK:          {balance}")
    print(f"Точность:             {precision}")
    print(f"Floor округление:     {rounded_amount}")
    print(f"Безопасно:            {rounded_amount} <= {balance} = {rounded_amount <= balance}")
    print()
    
    # Create order payload
    payload = {
        "market": "nockusdt",
        "side": "sell",
        "amount": str(rounded_amount),
        "type": "market"
    }
    
    print(f"Payload для API:")
    print(json.dumps(payload, indent=2))
    print()
    
    try:
        url = BASE_URL + "/trade/market/orders"
        headers = get_auth_headers()
        response = scraper.post(url, headers=headers, json=payload, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code in [200, 201]:
            result = response.json()
            print(f"\n✅ УСПЕХ! Ордер создан:")
            print(json.dumps(result, indent=2))
            
            # Try to cancel immediately (this is a test)
            if 'id' in result:
                order_id = result['id']
                print(f"\n⚠️ Отменяем тестовый ордер (ID: {order_id})...")
                try:
                    cancel_url = BASE_URL + f"/trade/market/orders/{order_id}/cancel"
                    cancel_response = scraper.post(cancel_url, headers=get_auth_headers(), timeout=30)
                    if cancel_response.status_code == 200:
                        print(f"✅ Ордер успешно отменен")
                    else:
                        print(f"⚠️ Статус отмены: {cancel_response.status_code}")
                        print(f"Response: {cancel_response.text}")
                except Exception as e:
                    print(f"⚠️ Ошибка отмены: {e}")
        else:
            print(f"\n❌ ОШИБКА: {response.status_code}")
            print(f"Response: {response.text}")
            try:
                error = response.json()
                print(f"Error JSON: {json.dumps(error, indent=2)}")
            except:
                pass
                
    except Exception as e:
        print(f"❌ ИСКЛЮЧЕНИЕ: {e}")
        import traceback
        traceback.print_exc()
    
    print("=" * 60)

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("❌ API credentials not found")
    else:
        test_nock_order_with_floor_rounding()
