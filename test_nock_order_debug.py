"""
Test script to debug NOCK order creation
"""
import os
import time
import hmac
import hashlib
import binascii
import cloudscraper
import json
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

def test_order_creation():
    scraper = cloudscraper.create_scraper()
    
    # Test different amount formats with SMALL amounts to avoid consuming balance
    # We're just trying to see what error messages the API returns
    test_cases = [
        {"amount": "0.01", "desc": "Min amount (string 0.01)"},
        {"amount": "0.0100", "desc": "Min amount with 4 decimals (0.0100)"},
        {"amount": 0.01, "desc": "Min amount (float 0.01)"},
        {"amount": "1.0000", "desc": "String 1.0000 (4 decimals)"},
        {"amount": "1", "desc": "String 1 (integer format)"},
        {"amount": 1.0, "desc": "Float 1.0"},
        # Now test with actual balance amount
        {"amount": "177.8397", "desc": "Actual balance rounded to 4 decimals"},
    ]
    
    for test in test_cases:
        payload = {
            "market": "nockusdt",
            "side": "sell",
            "amount": test["amount"],
            "type": "market"
        }
        
        print(f"\n{'='*60}")
        print(f"Testing: {test['desc']}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        try:
            url = BASE_URL + "/trade/market/orders"
            headers = get_auth_headers()
            response = scraper.post(url, headers=headers, json=payload, timeout=30)
            
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                print(f"✅ SUCCESS: {json.dumps(result, indent=2)}")
                
                # If successful, try to cancel it immediately
                if 'id' in result:
                    order_id = result['id']
                    print(f"⚠️ Order created with ID: {order_id}, attempting to cancel...")
                    try:
                        cancel_url = BASE_URL + f"/trade/market/orders/{order_id}/cancel"
                        cancel_response = scraper.post(cancel_url, headers=get_auth_headers(), timeout=30)
                        if cancel_response.status_code == 200:
                            print(f"✅ Order cancelled successfully")
                        else:
                            print(f"⚠️ Cancel status: {cancel_response.status_code} - {cancel_response.text}")
                    except Exception as cancel_error:
                        print(f"⚠️ Cancel failed: {cancel_error}")
                
                # Continue to next test
            else:
                print(f"❌ FAILED")
                print(f"Response Text: {response.text}")
                
                # Try to parse error details
                try:
                    error_json = response.json()
                    print(f"Error JSON: {json.dumps(error_json, indent=2)}")
                except:
                    pass
                    
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            
    print(f"\n{'='*60}")

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("❌ API credentials not found in .env")
    else:
        print(f"API Key: {API_KEY[:10]}...")
        print(f"Testing NOCK order creation...")
        test_order_creation()
