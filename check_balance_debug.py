"""
Check NOCK balance before testing
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

def get_balances():
    scraper = cloudscraper.create_scraper()
    
    # Try different endpoints
    endpoints = [
        "/trade/account/balances",
        "/account/balances"
    ]
    
    for endpoint in endpoints:
        try:
            url = BASE_URL + endpoint
            headers = get_auth_headers()
            response = scraper.get(url, headers=headers, timeout=30)
            
            print(f"Trying: {endpoint}")
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                balances = response.json()
                
                # Find NOCK balance
                if isinstance(balances, list):
                    nock = next((b for b in balances if b.get('currency', '').lower() == 'nock'), None)
                    if nock:
                        print(f"\n✅ NOCK Balance: {nock.get('balance', 0)}")
                        return nock
                elif isinstance(balances, dict):
                    # Might be different structure
                    print(f"Balances structure: {json.dumps(balances, indent=2)[:500]}")
                    nock_balance = balances.get('nock', balances.get('NOCK'))
                    if nock_balance:
                        print(f"\n✅ NOCKBalance: {nock_balance}")
                        return nock_balance
                        
                print(f"Full response: {json.dumps(balances, indent=2)[:1000]}")
                return balances
                
        except Exception as e:
            print(f"Error with {endpoint}: {e}")
            continue
    
    return None

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("❌ API credentials not found in .env")
    else:
        print(f"API Key: {API_KEY[:10]}...")
        print(f"\nChecking NOCK balance...")
        get_balances()
