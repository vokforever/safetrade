import requests
from datetime import datetime
import pytz
import hmac
import hashlib
import binascii
import time
import logging

class Client:
  def __init__(self, baseURL, key, secret):
    self.baseURL = baseURL
    self.key = key
    self.secret = secret
    self.headers = {}

  def get_authentication(self):
    nonce = str(int(time.time()) * 1000)  # Nonce in milliseconds
    signature = self.generate_signature(nonce, self.secret, self.key)
    return {
        "X-Auth-Apikey": self.key,
        "X-Auth-Nonce": nonce,
        "X-Auth-Signature": signature,
        "Content-Type": "application/json;charset=utf-8"
    }

  def get_api(self, url, query=None, headers=None):
    try:
        auth_headers = self.get_authentication()
        if headers:
            auth_headers.update(headers)
        
        logging.debug(f"Making GET request to: {self.baseURL + url}")
        if query:
            logging.debug(f"Query parameters: {query}")
        
        response = requests.get(self.baseURL + url, headers=auth_headers, params=query, timeout=30)
        
        logging.debug(f"Response status: {response.status_code}")
        logging.debug(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                logging.debug(f"Response data type: {type(data)}")
                if isinstance(data, dict):
                    logging.debug(f"Response keys: {list(data.keys())}")
                elif isinstance(data, list):
                    logging.debug(f"Response list length: {len(data)}")
                return data
            except Exception as e:
                logging.error(f"Failed to parse JSON response: {e}")
                logging.debug(f"Raw response text: {response.text[:500]}")
                return None
        else:
            logging.warning(f"API request failed with status {response.status_code}: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Connection error: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in get_api: {e}")
        return None

  def post_api(self, url, data=None, headers=None):
    try:
        auth_headers = self.get_authentication()
        if headers:
            auth_headers.update(headers)
        
        logging.debug(f"Making POST request to: {self.baseURL + url}")
        if data:
            logging.debug(f"POST data: {data}")
        
        response = requests.post(self.baseURL + url, headers=auth_headers, json=data, timeout=30)
        
        logging.debug(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            try:
                return response.json()
            except Exception as e:
                logging.error(f"Failed to parse JSON response: {e}")
                return None
        else:
            logging.warning(f"API request failed with status {response.status_code}: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Connection error: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in post_api: {e}")
        return None

  def generate_signature(self, nonce, key, secret):
    hash = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    # Concatenate nonce and key, then calculate the HMAC hash
    hash.update((nonce + key).encode())
    signature = hash.digest()

    # Convert the binary signature to hexadecimal representation
    signature_hex = binascii.hexlify(signature).decode()

    return signature_hex

  def get_orders(self, state=None, limit=100, offset=0):
    """Get orders with optional state filtering"""
    query = {"limit": limit, "offset": offset}
    if state:
        query["state"] = state
    return self.get_api("/trade/market/orders", query=query)

  def get_trade_history(self, market=None, limit=100, offset=0):
    """
    Get completed trade history with execution details
    Enhanced to handle different SafeTrade API response structures
    """
    query = {"limit": limit, "offset": offset}
    if market:
        query["market"] = market
    
    logging.info(f"Fetching trade history with query: {query}")
    
    # Try the main trades endpoint
    trades = self.get_api("/trade/market/trades", query=query)
    
    if trades:
        logging.info(f"Trade history response structure: {type(trades)}")
        if isinstance(trades, dict):
            logging.info(f"Trade history response keys: {list(trades.keys())}")
        elif isinstance(trades, list):
            logging.info(f"Trade history response length: {len(trades)}")
    
    return trades

  def get_completed_orders(self, market=None, limit=100, offset=0):
    """
    Get completed orders with execution details
    Enhanced to handle different SafeTrade API response structures
    """
    query = {"state": "done", "limit": limit, "offset": offset}
    if market:
        query["market"] = market
    
    logging.info(f"Fetching completed orders with query: {query}")
    
    # Try the orders endpoint with done state
    orders = self.get_api("/trade/market/orders", query=query)
    
    if orders:
        logging.info(f"Completed orders response structure: {type(orders)}")
        if isinstance(orders, dict):
            logging.info(f"Completed orders response keys: {list(orders.keys())}")
        elif isinstance(orders, list):
            logging.info(f"Completed orders response length: {len(orders)}")
    
    return orders

  def get_order_details(self, order_id):
    """
    Get detailed information about a specific order
    """
    return self.get_api(f"/trade/market/orders/{order_id}")

  def create_order(self, market, side, amount, price=None):
    data = {
        "market": market,
        "side": side,
        "amount": amount,
        "type": "limit" if price is not None else "market"
    }
    if price is not None:
        data["price"] = price
    return self.post_api("/trade/market/orders", data=data)
  
  def get_account_trades(self, market=None, limit=100, offset=0):
    """
    Alternative endpoint for getting account-specific trades
    """
    query = {"limit": limit, "offset": offset}
    if market:
        query["market"] = market
    
    logging.info(f"Fetching account trades with query: {query}")
    
    # Try account-specific trades endpoint
    trades = self.get_api("/trade/account/trades", query=query)
    
    if trades:
        logging.info(f"Account trades response structure: {type(trades)}")
        if isinstance(trades, dict):
            logging.info(f"Account trades response keys: {list(trades.keys())}")
        elif isinstance(trades, list):
            logging.info(f"Account trades response length: {len(trades)}")
    
    return trades
  
  def get_peatio_trades(self, market=None, limit=100, offset=0):
    """
    Alternative endpoint using Peatio format (some SafeTrade instances use this)
    """
    query = {"limit": limit, "offset": offset}
    if market:
        query["market"] = market
    
    logging.info(f"Fetching Peatio trades with query: {query}")
    
    # Try Peatio-style endpoint
    trades = self.get_api("/peatio/market/trades", query=query)
    
    if trades:
        logging.info(f"Peatio trades response structure: {type(trades)}")
        if isinstance(trades, dict):
            logging.info(f"Peatio trades response keys: {list(trades.keys())}")
        elif isinstance(trades, list):
            logging.info(f"Peatio trades response length: {len(trades)}")
    
    return trades
