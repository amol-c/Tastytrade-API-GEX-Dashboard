"""
Tradier API Client for GEX Dashboard
Replaces Tastytrade/dxFeed with Tradier REST API.
"""
import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

LIVE_KEY = os.getenv("LIVE_KEY", "")
SANDBOX_KEY = os.getenv("SANDBOX_KEY", "")
USE_SANDBOX = os.getenv("USE_SANDBOX", "false").lower() == "true"

BASE_URL = "https://sandbox.tradier.com" if USE_SANDBOX else "https://api.tradier.com"
TOKEN = SANDBOX_KEY if USE_SANDBOX else LIVE_KEY

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
}

def get_quote(symbol: str) -> dict:
    """GET /v1/markets/quotes — returns quote dict for a single symbol."""
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/markets/quotes",
            params={"symbols": symbol, "greeks": "false"},
            headers=HEADERS
        )
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("quotes", {})
        if not quotes or quotes == "null":
            return None
            
        quote = quotes.get("quote", {})
        if isinstance(quote, list):
            return quote[0] if quote else None
        return quote if quote else None
    except Exception as e:
        logger.error("Failed to fetch quote for %s: %s", symbol, e)
        return None

def get_underlying_price(symbol: str) -> float:
    """Get current underlying price."""
    quote = get_quote(symbol)
    if quote:
        return quote.get("last")
    return None

def get_vix_price() -> float:
    """Get current VIX value."""
    quote = get_quote("VIX")
    if quote:
        return quote.get("last")
    # Try alternative symbol
    quote = get_quote("$VIX.X")
    if quote:
        return quote.get("last")
    return None

def fetch_option_data(symbol: str, expiration: str) -> dict:
    """
    Fetch comprehensive option chain data mapped by symbol.
    Expiration should be in YYMMDD format (as provided by the dashboard).
    """
    # expiration in Tradier needs to be YYYY-MM-DD
    if len(expiration) == 6:
        # Assumes 20XX
        exp_date = f"20{expiration[0:2]}-{expiration[2:4]}-{expiration[4:6]}"
    else:
        exp_date = expiration
        
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/markets/options/chains",
            params={"symbol": symbol, "expiration": exp_date, "greeks": "true"},
            headers=HEADERS
        )
        resp.raise_for_status()
        options_data = resp.json()
        
        options_raw = options_data.get("options", {})
        if not options_raw or options_raw == "null":
            return {}
            
        options = options_raw.get("option", [])
        if isinstance(options, dict):
            options = [options]
            
        result = {}
        from utils.gex_calculator import parse_option_symbol

        for opt in options:
            opt_sym = opt.get("symbol")
            if not opt_sym:
                continue
                
            # Pre-parse symbol to get strike and type
            parsed = parse_option_symbol(opt_sym)
            if not parsed:
                continue

            greeks = opt.get("greeks")
            if not isinstance(greeks, dict):
                greeks = {}
            
            # Helper to safely convert to float
            def to_f(val, default=0.0):
                try:
                    return float(val) if val is not None else default
                except (ValueError, TypeError):
                    return default

            result[opt_sym] = {
                "gamma": to_f(greeks.get("gamma")),
                "delta": to_f(greeks.get("delta")),
                "vega": to_f(greeks.get("vega")),
                "iv": to_f(greeks.get("smv_vol") or greeks.get("bid_iv") or greeks.get("mid_iv")),
                "oi": int(to_f(opt.get("open_interest"), 0)),
                "volume": int(to_f(opt.get("volume"), 0)),
                "strike": parsed['strike'],
                "type": parsed['type']
            }
        return result
    except Exception as e:
        logger.error("Failed to fetch options chain for %s: %s", symbol, e)
        return {}

