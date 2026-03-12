import sys
from utils.tradier_api import get_underlying_price, fetch_option_data

try:
    price = get_underlying_price("SPX")
    print(f"SPX Price: {price}")
    
    # We use 260320 as expiration (Mar 20, 2026)
    opts = fetch_option_data("SPX", "260320")
    print(f"Options Count: {len(opts)}")
    
    # Check if a few options have right data
    if len(opts) > 0:
        first_opt = list(opts.keys())[0]
        print(f"First Option {first_opt}: {opts[first_opt]}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
