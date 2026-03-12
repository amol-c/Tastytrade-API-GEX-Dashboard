import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

LIVE_KEY = os.getenv("LIVE_KEY", "")
SANDBOX_KEY = os.getenv("SANDBOX_KEY", "")
USE_SANDBOX = os.getenv("USE_SANDBOX", "false").lower() == "true"

BASE_URL = "https://sandbox.tradier.com" if USE_SANDBOX else "https://api.tradier.com"
TOKEN = SANDBOX_KEY if USE_SANDBOX else LIVE_KEY

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
}

def debug_tradier_spx_atm(symbol="SPX", expiration="260320"):
    # Convert YYMMDD to YYYY-MM-DD
    exp_date = f"20{expiration[0:2]}-{expiration[2:4]}-{expiration[4:6]}"
    
    # Get price first
    print(f"Fetching price for {symbol}...")
    resp = requests.get(f"{BASE_URL}/v1/markets/quotes", params={"symbols": symbol}, headers=HEADERS)
    price = resp.json().get("quotes", {}).get("quote", {}).get("last", 6000.0)
    print(f"Current Price: {price}")
    
    print(f"Fetching chain for {symbol} expiring {exp_date} from {BASE_URL}...")
    
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/markets/options/chains",
            params={"symbol": symbol, "expiration": exp_date, "greeks": "true"},
            headers=HEADERS
        )
        resp.raise_for_status()
        data = resp.json()
        
        options = data.get("options", {}).get("option", [])
        if isinstance(options, dict):
            options = [options]
            
        print(f"Total options found: {len(options)}")
        
        from utils.gex_calculator import parse_option_symbol
        
        # Look for ATM options
        atm_options = []
        for opt in options:
            sym = opt.get("symbol")
            parsed = parse_option_symbol(sym)
            if parsed and abs(parsed['strike'] - price) < 50:
                atm_options.append(opt)
        
        print(f"Found {len(atm_options)} options near ATM.")
        
        for opt in atm_options[:10]:
            print(f"\nOption: {opt.get('symbol')}")
            print(f"  Strike: {parse_option_symbol(opt.get('symbol'))['strike']}")
            print(f"  OI: {opt.get('open_interest')}")
            print(f"  Greeks: {opt.get('greeks')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_tradier_spx_atm()
