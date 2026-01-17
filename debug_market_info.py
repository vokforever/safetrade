import cloudscraper
import json

def get_market_info():
    url = "https://safe.trade/api/v2/trade/public/markets"
    scraper = cloudscraper.create_scraper()
    try:
        response = scraper.get(url)
        response.raise_for_status()
        markets = response.json()
        
        print(f"Total markets found: {len(markets)}")
        
        nock_markets = [m for m in markets if 'nock' in m.get('name', '').lower() or 'nock' in m.get('base_unit', '').lower()]
        
        if nock_markets:
            print(f"Found {len(nock_markets)} NOCK markets:")
            print(json.dumps(nock_markets, indent=2))
        else:
            print("No markets containing 'nock' found.")
            # Print first 5 markets to see structure
            print("First 5 markets:")
            print(json.dumps(markets[:5], indent=2))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_market_info()
