"""
Simple GEX Dashboard - Direct WebSocket approach (no background threads)
Fetches data once when you click "Fetch Data", then displays it
Works on weekends with Friday's closing data
"""
import json
import logging
import math
import os
import ssl
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta

import certifi
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from websocket import create_connection

from components.account_settings import render_account_settings
from components.charm_display import render_charm_section
from components.combined_flow_display import render_combined_flow_section
from components.combined_hedge_display import render_combined_hedge
from components.dashboard_layout import (
    render_ai_prompt_expander,
    render_key_levels_expander,
    render_tier1_summary,
    render_tier2_exposure,
    render_tier3_flows,
    render_tier4_structure,
)
from components.greek_dominance import render_greek_dominance_timer
from components.market_analysis_display import render_bias_help_expander, render_market_analysis_header
from components.sentiment_display import render_sentiment_section
from components.vanna_display import render_vanna_section_with_price
from components.vex_display import render_vex_section
from components.vix_display import render_vix_section
from utils.auth import ensure_streamer_token
from utils.charm_history import CharmHistoryTracker, calculate_es_futures_equivalent
from utils.delta_flow_calculator import DeltaFlowCalculator
from utils.delta_flow_history import DeltaFlowHistoryTracker
from utils.gex_calculator import GEXCalculator
from utils.tick_data_manager import TickDataManager
from components.delta_flow_display import render_delta_flow_section
from components.tick_display import render_tick_data_expander, render_tick_summary
from components.top_strikes_table import render_top_strikes_table
from utils.market_analyzer import MarketAnalyzer
from utils.sentiment_calculator import SentimentCalculator
from utils.vanna_calculator import VannaCalculator
from utils.vanna_history import VannaHistoryTracker, calculate_es_futures_from_vanna
from utils.vix_tracker import get_vix_price, determine_iv_direction, calculate_vix_slope, VIXHistoryTracker, VIXSlope


# Configure logging - use temp directory for frozen apps
def _get_log_path():
    if getattr(sys, 'frozen', False):
        # Running as frozen app - use temp directory
        log_dir = os.path.join(tempfile.gettempdir(), 'gex_dashboard')
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, 'dashboard.log')
    else:
        # Development - use local logs directory
        os.makedirs('logs', exist_ok=True)
        return 'logs/dashboard.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_get_log_path()),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Preset symbol configuration
PRESET_SYMBOLS = {
    "SPX": {"option_prefix": "SPXW", "default_price": 6000, "increment": 5},
    "NDX": {"option_prefix": "NDXP", "default_price": 20000, "increment": 25},
    "SPY": {"option_prefix": "SPY", "default_price": 680, "increment": 1},
    "QQQ": {"option_prefix": "QQQ", "default_price": 612, "increment": 1},
    "IWM": {"option_prefix": "IWM", "default_price": 240, "increment": 1},
    "DIA": {"option_prefix": "DIA", "default_price": 450, "increment": 1},
}

DXFEED_URL = "wss://tasty-openapi-ws.dxfeed.com/realtime"


def connect_websocket(token):
    """Connect to dxFeed WebSocket"""
    # Create SSL context with certifi certificates (fixes frozen app SSL issues)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    ws = create_connection(DXFEED_URL, timeout=10, sslopt={"context": ssl_context})

    # SETUP
    ws.send(json.dumps({
        "type": "SETUP",
        "channel": 0,
        "keepaliveTimeout": 60,
        "acceptKeepaliveTimeout": 60,
        "version": "1.0.0"
    }))
    data = ws.recv()
    logger.info(f"SETUP response: {data[:200] if data else 'empty'}")
    if not data:
        raise ConnectionError("WebSocket returned empty response during SETUP")

    # AUTH
    while True:
        data = ws.recv()
        logger.info(f"AUTH response: {data[:200] if data else 'empty'}")
        if not data:
            raise ConnectionError(f"WebSocket returned empty response during AUTH")
        msg = json.loads(data)
        if msg.get("type") == "AUTH_STATE":
            if msg["state"] == "UNAUTHORIZED":
                ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": token}))
            elif msg["state"] == "AUTHORIZED":
                break

    # FEED channel
    ws.send(json.dumps({
        "type": "CHANNEL_REQUEST",
        "channel": 1,
        "service": "FEED",
        "parameters": {"contract": "AUTO"}
    }))
    data = ws.recv()
    logger.info(f"CHANNEL_REQUEST response: {data[:200] if data else 'empty'}")
    if not data:
        raise ConnectionError("WebSocket returned empty response during CHANNEL_REQUEST")
    msg = json.loads(data)

    return ws


def get_underlying_price(ws, symbol):
    """Get underlying price - tries Trade first (most accurate), falls back to Quote midpoint"""
    ws.send(json.dumps({
        "type": "FEED_SUBSCRIPTION",
        "channel": 1,
        "add": [
            {"symbol": symbol, "type": "Trade"},
            {"symbol": symbol, "type": "Quote"}
        ]
    }))

    trade_price = None
    quote_mid = None
    start = time.time()

    while time.time() - start < 5:
        try:
            ws.settimeout(1)
            msg = json.loads(ws.recv())
            if msg.get("type") == "FEED_DATA":
                for data in msg.get("data", []):
                    if data.get("eventSymbol") == symbol:
                        event_type = data.get("eventType")

                        # Prefer Trade price (last trade)
                        if event_type == "Trade":
                            price = data.get("price")
                            if price:
                                trade_price = float(price)

                        # Fallback: Quote midpoint
                        elif event_type == "Quote":
                            bid = data.get("bidPrice")
                            ask = data.get("askPrice")
                            if bid and ask:
                                try:
                                    quote_mid = (float(bid) + float(ask)) / 2
                                except (ValueError, TypeError):
                                    pass

            # Return Trade price if we have it, otherwise Quote mid
            if trade_price:
                return trade_price
            elif quote_mid:
                return quote_mid

        except:
            continue

    # Return whichever we got
    return trade_price or quote_mid


def generate_option_symbols(center_price, option_prefix, expiration, strikes_up, strikes_down, increment):
    """Generate option symbols around center price"""
    center_strike = round(center_price / increment) * increment
    strikes = []

    for i in range(-strikes_down, strikes_up + 1):
        strike = center_strike + (i * increment)
        strikes.append(strike)

    options = []
    for strike in strikes:
        # Format strike: use int if whole number, else keep decimal
        if strike == int(strike):
            strike_str = str(int(strike))
        else:
            strike_str = str(strike)

        options.append(f".{option_prefix}{expiration}C{strike_str}")
        options.append(f".{option_prefix}{expiration}P{strike_str}")

    return options


def fetch_option_data(ws, symbols, wait_seconds=15, tick_manager=None):
    """
    Fetch Greeks, Summary (OI), Trade (Volume), and TimeAndSale for options.

    Args:
        ws: WebSocket connection
        symbols: List of option symbols
        wait_seconds: How long to collect data
        tick_manager: Optional TickDataManager for real-time OI estimation
    """
    subscriptions = []
    for symbol in symbols:
        subscriptions.extend([
            {"symbol": symbol, "type": "Greeks"},
            {"symbol": symbol, "type": "Summary"},
            {"symbol": symbol, "type": "Trade"},
        ])

    # Add TimeAndSale subscriptions if tick_manager provided
    if tick_manager:
        subscriptions.extend(tick_manager.generate_subscriptions(symbols))

    ws.send(json.dumps({
        "type": "FEED_SUBSCRIPTION",
        "channel": 1,
        "add": subscriptions
    }))

    data = {}
    start = time.time()

    while time.time() - start < wait_seconds:
        try:
            ws.settimeout(0.5)
            msg = json.loads(ws.recv())

            if msg.get("type") == "FEED_DATA":
                # Process TimeAndSale ticks if manager provided
                if tick_manager:
                    tick_manager.process_message(msg, set_opening_oi=True)

                for item in msg.get("data", []):
                    symbol = item.get("eventSymbol")
                    event_type = item.get("eventType")

                    if symbol not in data:
                        data[symbol] = {}

                    if event_type == "Greeks":
                        data[symbol]["gamma"] = item.get("gamma")
                        data[symbol]["delta"] = item.get("delta")
                        data[symbol]["vega"] = item.get("vega")
                        data[symbol]["iv"] = item.get("volatility")
                    elif event_type == "Summary":
                        data[symbol]["oi"] = item.get("openInterest")
                    elif event_type == "Trade":
                        # Cumulative volume from Trade events
                        data[symbol]["volume"] = item.get("dayVolume", 0)
        except:
            continue

    # Apply adjusted OI if tick_manager provided
    if tick_manager:
        data = tick_manager.apply_adjusted_oi(data)
        tick_manager.maybe_save()

    return data




def run_market_analysis(symbol, price, expiration, option_data, gex_metrics, vanna_data=None):
    """Run unified market analysis combining GEX, charm, vanna, and sentiment."""
    from utils.gex_calculator import parse_option_symbol

    # Build options data with required fields
    options_data = {}
    total_call_vol = 0
    total_put_vol = 0

    for sym, data in option_data.items():
        parsed = parse_option_symbol(sym)
        if parsed:
            options_data[sym] = {
                'iv': data.get('iv'),
                'oi': data.get('oi'),
                'strike': parsed['strike'],
                'type': parsed['type'],
            }
            vol = data.get('volume', 0) or 0
            try:
                vol = float(vol)
            except (TypeError, ValueError) as e:
                logger.warning(f"Could not convert volume '{vol}' to float for {sym}: {e}")
                vol = 0
            if parsed['type'] == 'C':
                total_call_vol += vol
            else:
                total_put_vol += vol

    analyzer = MarketAnalyzer()
    return analyzer.analyze({
        'symbol': symbol,
        'spot_price': price,
        'expiry': expiration,
        'gex_metrics': gex_metrics,
        'options_data': options_data,
        'volume_data': {
            'total_call_volume': total_call_vol,
            'total_put_volume': total_put_vol,
        },
        'vanna_data': vanna_data or {},
    })


def aggregate_by_strike(option_data, tick_manager=None):
    """Aggregate volume and OI by strike from option data"""
    from utils.gex_calculator import parse_option_symbol

    strike_data = {}

    for symbol, data in option_data.items():
        parsed = parse_option_symbol(symbol)
        if not parsed:
            continue

        strike = parsed['strike']
        opt_type = parsed['type']

        if strike not in strike_data:
            strike_data[strike] = {
                'call_oi': 0,
                'put_oi': 0,
                'call_volume': 0,
                'put_volume': 0,
                'call_iv': None,
                'put_iv': None,
                'buy_volume': 0,
                'sell_volume': 0,
                'oi_adjusted': False,
            }

        # Convert to numbers (might be strings from WebSocket or NaN)
        try:
            oi = float(data.get('oi', 0) or 0)
            if math.isnan(oi):
                oi = 0
        except (ValueError, TypeError):
            oi = 0

        try:
            volume = float(data.get('volume', 0) or 0)
            if math.isnan(volume):
                volume = 0
        except (ValueError, TypeError):
            volume = 0

        iv = data.get('iv')

        if opt_type == 'C':
            strike_data[strike]['call_oi'] += int(oi)
            strike_data[strike]['call_volume'] += int(volume)
            if iv:
                strike_data[strike]['call_iv'] = iv
        else:
            strike_data[strike]['put_oi'] += int(oi)
            strike_data[strike]['put_volume'] += int(volume)
            if iv:
                strike_data[strike]['put_iv'] = iv

        # Add tick data if available
        if tick_manager:
            breakdown = tick_manager.get_volume_breakdown(symbol)
            strike_data[strike]['buy_volume'] += breakdown['buy_volume']
            strike_data[strike]['sell_volume'] += breakdown['sell_volume']
            if data.get('oi_adjusted'):
                strike_data[strike]['oi_adjusted'] = True

    # Convert to DataFrame
    rows = []
    for strike, data in strike_data.items():
        net_flow = data['buy_volume'] - data['sell_volume']
        rows.append({
            'strike': strike,
            'call_oi': data['call_oi'],
            'put_oi': data['put_oi'],
            'call_volume': data['call_volume'],
            'put_volume': data['put_volume'],
            'total_oi': data['call_oi'] + data['put_oi'],
            'total_volume': data['call_volume'] + data['put_volume'],
            'call_iv': data['call_iv'],
            'put_iv': data['put_iv'],
            'buy_volume': data['buy_volume'],
            'sell_volume': data['sell_volume'],
            'net_flow': net_flow,
            'oi_adjusted': data['oi_adjusted'],
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('strike').reset_index(drop=True)
    return df


def main():
    st.set_page_config(page_title="GEX Dashboard", page_icon="📊", layout="wide")
    st.title("📊 Options Gamma Exposure Dashboard")

    # Initialize session state
    if 'data_fetched' not in st.session_state:
        st.session_state.data_fetched = False
    if 'gex_calculator' not in st.session_state:
        st.session_state.gex_calculator = None
    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = False
    if 'last_fetch_time' not in st.session_state:
        st.session_state.last_fetch_time = 0
    if 'option_data' not in st.session_state:
        st.session_state.option_data = {}
    if 'gex_view' not in st.session_state:
        st.session_state.gex_view = "Calls vs Puts"
    if 'volume_view' not in st.session_state:
        st.session_state.volume_view = "Calls vs Puts"
    if 'tick_data_manager' not in st.session_state:
        st.session_state.tick_data_manager = None

    # Sidebar controls
    with st.sidebar:
        st.header("⚙️ Settings")

        # Symbol selection: Preset or Custom
        symbol_mode = st.radio("Symbol Mode", ["Preset", "Custom"], horizontal=True)

        if symbol_mode == "Preset":
            symbol = st.selectbox("Underlying", list(PRESET_SYMBOLS.keys()))
            config = PRESET_SYMBOLS[symbol]
            option_prefix = config["option_prefix"]
            increment = config["increment"]
            default_price = config["default_price"]
        else:
            st.caption("Enter any symbol and its option parameters")
            symbol = st.text_input("Underlying Symbol", value="AAPL", max_chars=10).upper()
            option_prefix = st.text_input("Option Prefix", value="AAPL", max_chars=10,
                                         help="Usually same as underlying (e.g., AAPL, TSLA)").upper()
            increment = st.number_input("Strike Increment", min_value=0.5, max_value=100.0, value=2.5, step=0.5,
                                       help="SPY/QQQ: 1, AAPL: 2.5, TSLA: 5, SPX: 5, NDX: 25")
            default_price = st.number_input("Fallback Price", min_value=1.0, max_value=100000.0, value=100.0,
                                          help="Used if live price unavailable")

        # Default expiration to today's date
        default_exp = datetime.now().strftime("%y%m%d")

        expiration = st.text_input(
            "Expiration (YYMMDD)",
            value=default_exp,
            max_chars=6,
            help="Today's date shown by default. Change to any option expiration (e.g., 251219 for Dec 19, 2025)"
        )

        with st.expander("Strike Range"):
            strikes_up = st.number_input("Strikes above center", min_value=5, max_value=50, value=25)
            strikes_down = st.number_input("Strikes below center", min_value=5, max_value=50, value=25)

        st.divider()

        # Auto-refresh controls
        st.subheader("🔄 Auto-Refresh")
        st.session_state.auto_refresh = st.checkbox(
            "Enable auto-refresh",
            value=st.session_state.auto_refresh,
            help="Automatically refetch data every X seconds"
        )

        if st.session_state.auto_refresh:
            if 'refresh_interval' not in st.session_state:
                st.session_state.refresh_interval = 60
            st.session_state.refresh_interval = st.slider(
                "Refresh interval (seconds)",
                min_value=30,
                max_value=300,
                value=st.session_state.refresh_interval,
                step=10,
                help="How often to refresh data"
            )
            refresh_interval = st.session_state.refresh_interval
        else:
            refresh_interval = st.session_state.get('refresh_interval', 60)

        st.divider()

        # Manual fetch button
        fetch_triggered = st.button("🔄 Fetch Data", type="primary", use_container_width=True)

        # Account settings
        render_account_settings()

        # Auto-fetch logic
        if st.session_state.auto_refresh:
            current_time = time.time()
            if current_time - st.session_state.last_fetch_time >= refresh_interval:
                fetch_triggered = True

        if fetch_triggered:
            with st.spinner(f"Fetching {symbol} data..."):
                try:
                    # Get token and connect
                    token = ensure_streamer_token()
                    ws = connect_websocket(token)

                    # Get underlying price
                    st.info(f"📊 Getting {symbol} price...")
                    price = get_underlying_price(ws, symbol)

                    if not price:
                        price = default_price
                        st.warning(f"⚠️ Using fallback price: ${price}")
                    else:
                        st.success(f"✅ {symbol} Price: ${price:,.2f}")

                    # Generate option symbols
                    option_symbols = generate_option_symbols(
                        price,
                        option_prefix,
                        expiration,
                        strikes_up,
                        strikes_down,
                        increment
                    )

                    st.info(f"📡 Fetching data for {len(option_symbols)} options...")

                    # Initialize or update tick data manager for real-time OI
                    tick_manager = st.session_state.tick_data_manager
                    if tick_manager is None or tick_manager.expiry != expiration:
                        tick_manager = TickDataManager(expiry=expiration)
                        st.session_state.tick_data_manager = tick_manager
                        logger.info(f"Created TickDataManager for expiry {expiration}")

                    # Fetch option data with tick accumulation
                    option_data = fetch_option_data(ws, option_symbols, wait_seconds=20, tick_manager=tick_manager)

                    # Fetch VIX before closing WebSocket
                    current_vix = get_vix_price(ws, timeout=3)

                    ws.close()

                    # Calculate GEX
                    calc = GEXCalculator()
                    calc.update_spot_price(price)

                    for symbol_name, data in option_data.items():
                        if "gamma" in data and "oi" in data:
                            gamma = data["gamma"]
                            oi = data["oi"]
                            if gamma is not None and oi is not None:
                                calc.update_gamma(symbol_name, gamma, oi)

                    # Store in session state
                    st.session_state.gex_calculator = calc
                    st.session_state.option_data = option_data
                    st.session_state.data_fetched = True
                    st.session_state.underlying_price = price
                    st.session_state.symbol = symbol
                    st.session_state.expiration = expiration
                    st.session_state.option_count = len(option_data)
                    st.session_state.last_fetch_time = time.time()

                    # Track VIX history and calculate slope-based IV direction
                    iv_direction = 'FLAT'
                    iv_change_pct = 0.0
                    vix_slope = None
                    if current_vix:
                        today_str = datetime.now().strftime("%y%m%d")
                        vix_tracker = VIXHistoryTracker(date_str=today_str)

                        # Add current reading first
                        vix_tracker.add_record(current_vix, 'PENDING', 0.0)

                        # Calculate slope over past hour for trend detection
                        vix_slope = vix_tracker.get_slope(window_minutes=60)
                        iv_direction = vix_slope.direction
                        iv_change_pct = vix_slope.pct_per_hour

                        # Update the record with calculated direction
                        if vix_tracker.history:
                            vix_tracker.history[-1]['direction'] = iv_direction
                            vix_tracker.history[-1]['change_pct'] = iv_change_pct
                            vix_tracker._save_history()

                        st.session_state.current_vix = current_vix
                        st.session_state.iv_direction = iv_direction
                        st.session_state.iv_change_pct = iv_change_pct
                        st.session_state.vix_slope = vix_slope

                    # Calculate Vanna (before market analysis so it can be included in bias)
                    vanna_calc = VannaCalculator()
                    vanna_result = vanna_calc.calculate_current_vanna(
                        options_data=option_data,
                        spot=price,
                        expiry_str=expiration,
                        iv_direction=iv_direction,
                    )

                    # Prepare vanna data for market analysis
                    vanna_data = None
                    if vanna_result:
                        st.session_state.vanna_result = vanna_result
                        vanna_data = {
                            'net_vanna': vanna_result.net_vanna,
                            'flow_direction': vanna_result.flow_direction.value,
                            'iv_direction': iv_direction,
                        }
                        # Track vanna history
                        vanna_tracker = VannaHistoryTracker(expiry=expiration)
                        vanna_tracker.add_record(
                            spot_price=price,
                            net_vanna=vanna_result.net_vanna,
                            flow_direction=vanna_result.flow_direction.value,
                            iv_direction=iv_direction,
                            expiry=expiration,
                        )

                    # Run market analysis with vanna included
                    st.session_state.market_analysis = run_market_analysis(
                        symbol, price, expiration, option_data, calc.get_total_gex_metrics(), vanna_data
                    )

                    # Track charm history
                    analysis = st.session_state.market_analysis
                    if analysis and analysis.charm_flow.net_charm is not None:
                        charm_tracker = CharmHistoryTracker(expiry=expiration)
                        charm_tracker.add_record(
                            spot_price=price,
                            net_charm=analysis.charm_flow.net_charm,
                            flow_direction=analysis.charm_flow.direction,
                            expiry=expiration,
                        )

                    # Set up Delta Flow Calculator for tick data processing
                    # Build greeks_data from option_data for delta weighting
                    greeks_data = {
                        symbol: {"delta": data.get("delta", 0)}
                        for symbol, data in option_data.items()
                        if data.get("delta") is not None
                    }

                    # Create or reuse delta flow calculator
                    if 'delta_flow_calculator' not in st.session_state:
                        st.session_state.delta_flow_calculator = DeltaFlowCalculator()
                    delta_calc = st.session_state.delta_flow_calculator

                    # Wire up calculator with tick manager for future messages
                    tick_manager.set_delta_calculator(delta_calc)
                    tick_manager.set_greeks_data(greeks_data)
                    st.session_state.greeks_data = greeks_data

                    # Track delta flow history
                    if delta_calc.trade_count > 0:
                        delta_tracker = DeltaFlowHistoryTracker(expiry=expiration)
                        delta_tracker.add_record(
                            spot_price=price,
                            cumulative_customer_delta=delta_calc.cumulative_customer_delta,
                            flow_direction=delta_calc.get_flow_direction().value,
                            trade_count=delta_calc.trade_count,
                        )

                    greeks_count = sum(1 for d in option_data.values() if "gamma" in d)
                    oi_count = sum(1 for d in option_data.values() if "oi" in d)
                    volume_count = sum(1 for d in option_data.values() if "volume" in d)

                    st.success(f"✅ Data fetched! Greeks: {greeks_count}, OI: {oi_count}")
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Error: {e}")
                    st.code(traceback.format_exc())

        st.divider()

        if st.session_state.data_fetched:
            st.metric(f"{st.session_state.symbol} Price", f"${st.session_state.underlying_price:,.2f}")
            st.caption(f"Options: {st.session_state.option_count}")

            # Show last fetch time
            if st.session_state.last_fetch_time > 0:
                elapsed = time.time() - st.session_state.last_fetch_time
                st.caption(f"⏱️ Last fetch: {int(elapsed)}s ago")

                if st.session_state.auto_refresh:
                    next_refresh = max(0, refresh_interval - elapsed)

                    # Simple countdown display with color coding
                    if next_refresh <= 5:
                        # About to refresh - red warning
                        st.error(f"🔄 **REFRESHING IN {int(next_refresh)}s**")
                    elif next_refresh <= 15:
                        # Getting close - yellow warning
                        st.warning(f"🔄 Next refresh: **{int(next_refresh)}s**")
                    else:
                        # Plenty of time - green info
                        st.success(f"🔄 Next refresh: **{int(next_refresh)}s**")

                    # Progress bar showing time remaining
                    progress = (refresh_interval - elapsed) / refresh_interval
                    st.progress(max(0.0, min(1.0, progress)))

    # Main display
    if not st.session_state.data_fetched:
        st.info("👈 Configure settings and click 'Fetch Data' to load GEX data")
        st.caption("💡 Works on weekends! Shows Friday's closing data.")
        return

    # Get GEX data
    calc = st.session_state.gex_calculator
    gex_df = calc.get_gex_by_strike()
    metrics = calc.get_total_gex_metrics()

    if gex_df.empty:
        st.warning("⚠️ No GEX data available. Try fetching again or check different expiration.")
        return

    # ============================================================
    # TIER 1: SUMMARY
    # ============================================================
    if 'market_analysis' in st.session_state and st.session_state.market_analysis:
        analysis = st.session_state.market_analysis
        expiry = st.session_state.get('expiration', '')

        render_tier1_summary()
        render_greek_dominance_timer(expiry)
        render_bias_help_expander()
        render_market_analysis_header(analysis)
        render_sentiment_section(metrics, aggregate_by_strike(st.session_state.option_data, st.session_state.tick_data_manager))
        render_key_levels_expander(analysis)

    # Tick Data Summary (Real-Time OI Estimation)
    if st.session_state.tick_data_manager:
        render_tick_data_expander(st.session_state.tick_data_manager)

    # ============================================================
    # TIER 2: EXPOSURE CHARTS
    # ============================================================
    render_tier2_exposure()

    # GEX Chart
    col1, col2 = st.columns([2, 1])

    with col1:
        # GEX View Selector
        gex_view = st.radio(
            "GEX View",
            ["Calls vs Puts", "Net GEX", "Absolute GEX"],
            index=["Calls vs Puts", "Net GEX", "Absolute GEX"].index(st.session_state.gex_view),
            key="gex_view_radio",
            horizontal=True,
            help="Calls vs Puts: Separate bars | Net GEX: Call-Put | Absolute GEX: |Net| magnitude"
        )
        st.session_state.gex_view = gex_view

        # Create chart based on selected view
        fig = go.Figure()

        if gex_view == "Calls vs Puts":
            # Calls = Positive Gamma (Stabilizing), Puts = Negative Gamma (Destabilizing)
            fig.add_trace(go.Bar(
                x=gex_df['strike'],
                y=gex_df['call_gex'],
                name='Positive GEX (Calls)',
                marker_color='green'
            ))
            fig.add_trace(go.Bar(
                x=gex_df['strike'],
                y=-gex_df['put_gex'],
                name='Negative GEX (Puts)',
                marker_color='red'
            ))
            barmode = 'relative'
            yaxis_title = 'Dealer Gamma Exposure ($)'

        elif gex_view == "Net GEX":
            # Net GEX: Positive - Negative (determines dealer stance)
            colors = ['green' if x >= 0 else 'red' for x in gex_df['net_gex']]
            fig.add_trace(go.Bar(
                x=gex_df['strike'],
                y=gex_df['net_gex'],
                name='Net Dealer GEX',
                marker_color=colors
            ))
            barmode = 'group'
            yaxis_title = 'Net Dealer GEX ($) - Green=Stabilizing, Red=Destabilizing'

        else:  # Absolute GEX
            # Absolute Net GEX: |Call - Put| (always positive)
            abs_gex = abs(gex_df['net_gex'])
            fig.add_trace(go.Bar(
                x=gex_df['strike'],
                y=abs_gex,
                name='|Net GEX|',
                marker_color='blue'
            ))
            barmode = 'group'
            yaxis_title = 'Absolute Net GEX ($)'

        # Add vertical line at underlying price
        fig.add_vline(
            x=st.session_state.underlying_price,
            line_dash="dash",
            line_color="orange",
            line_width=2,
            annotation_text=f"${st.session_state.underlying_price:,.2f}",
            annotation_position="top"
        )

        # Add vertical line at Zero Gamma level (Gamma Flip)
        if metrics.get('zero_gamma'):
            zero_gamma = metrics['zero_gamma']
            fig.add_vline(
                x=zero_gamma,
                line_dash="dot",
                line_color="purple",
                line_width=2,
                annotation_text=f"Zero Γ: ${zero_gamma:,.2f}",
                annotation_position="top"
            )

        # Format expiration for display
        exp_display = st.session_state.expiration
        try:
            exp_date = datetime.strptime(st.session_state.expiration, "%y%m%d")
            exp_display = exp_date.strftime("%b %d, %Y")
        except:
            pass

        fig.update_layout(
            title=f'{st.session_state.symbol} Gamma Exposure by Strike - {gex_view} (Exp: {exp_display})',
            xaxis_title='Strike Price',
            yaxis_title=yaxis_title,
            barmode=barmode,
            template='plotly_white',
            height=500
        )

        st.plotly_chart(fig, width='stretch')

    with col2:
        st.subheader("📈 Dealer Gamma Exposure")

        # Determine dealer stance
        net_gex = metrics['net_gex']
        if net_gex > 0:
            dealer_stance = "🟢 Positive Gamma (Stabilizing)"
        else:
            dealer_stance = "🔴 Negative Gamma (Destabilizing)"

        st.markdown(f"**Dealer Stance:** {dealer_stance}")

        st.metric(
            "Positive Gamma (Calls)",
            f"${metrics['total_call_gex']:,.0f}",
            help="Dealers are long calls (institutions sold). Stabilizing - dealers sell rallies, buy dips."
        )
        st.metric(
            "Negative Gamma (Puts)",
            f"${metrics['total_put_gex']:,.0f}",
            help="Dealers are short puts (institutions bought). Destabilizing - dealers sell dips, buy rallies."
        )
        st.metric(
            "Net Dealer Gamma",
            f"${net_gex:,.0f}",
            delta=dealer_stance.split(" ", 1)[1],
            delta_color="normal" if net_gex > 0 else "inverse",
            help="Net = Positive Gamma - Negative Gamma. Positive = stabilizing, Negative = destabilizing."
        )

        if metrics['max_gex_strike']:
            st.divider()
            st.metric(
                "Max GEX Strike",
                f"${metrics['max_gex_strike']:,.0f}",
                help="Strike with highest absolute gamma. Acts as a 'magnet' - price tends to gravitate here."
            )

        if metrics.get('zero_gamma'):
            st.divider()
            zero_gamma = metrics['zero_gamma']
            spot = st.session_state.underlying_price
            if spot > zero_gamma:
                flip_status = "📍 Spot ABOVE flip (Positive Gamma)"
            else:
                flip_status = "📍 Spot BELOW flip (Negative Gamma)"

            st.metric(
                "Zero Gamma (Flip)",
                f"${zero_gamma:,.2f}",
                help="Strike where dealer gamma flips from positive to negative. Above = stabilizing, Below = destabilizing."
            )
            st.caption(flip_status)

    # VEx (Vanna Exposure) Section
    st.divider()
    vanna_calc = VannaCalculator()
    strike_vex = vanna_calc.calculate_vex_by_strike(
        options_data=st.session_state.option_data,
        spot=st.session_state.underlying_price,
        expiry_str=st.session_state.expiration,
    )
    vex_metrics = vanna_calc.get_vex_metrics(strike_vex) if strike_vex else {}

    render_vex_section(
        strike_vex=strike_vex,
        vex_metrics=vex_metrics,
        symbol=st.session_state.symbol,
        spot_price=st.session_state.underlying_price,
        expiry=st.session_state.expiration,
    )

    # Combined Flow Section (GEX + VEx + IV)
    st.divider()
    iv_direction = st.session_state.get('iv_direction', 'FLAT')
    vix_slope = st.session_state.get('vix_slope')
    iv_slope = vix_slope.normalized_slope if vix_slope else 0.0

    # Convert gex_df to dict format
    gex_by_strike = {}
    for _, row in gex_df.iterrows():
        gex_by_strike[row['strike']] = {
            'call_gex': row['call_gex'],
            'put_gex': row['put_gex'],
            'net_gex': row['net_gex'],
        }

    render_combined_flow_section(
        gex_by_strike=gex_by_strike,
        vex_by_strike=strike_vex,
        iv_direction=iv_direction,
        symbol=st.session_state.symbol,
        spot_price=st.session_state.underlying_price,
        expiry=st.session_state.expiration,
        iv_slope=iv_slope,
    )

    # Aggregate data by strike (used for IV Skew and Volume/OI)
    strike_df = aggregate_by_strike(st.session_state.option_data, st.session_state.tick_data_manager)

    # ============================================================
    # TIER 3: GREEK FLOWS (Time Series)
    # ============================================================
    if 'market_analysis' in st.session_state and st.session_state.market_analysis:
        analysis = st.session_state.market_analysis
        expiry = st.session_state.get('expiration', '')

        render_tier3_flows()
        today_str = datetime.now().strftime("%y%m%d")

        # VIX Section
        current_vix = st.session_state.get('current_vix')
        iv_direction = st.session_state.get('iv_direction', 'FLAT')
        iv_change_pct = st.session_state.get('iv_change_pct', 0.0)
        vix_slope = st.session_state.get('vix_slope')

        if current_vix:
            render_vix_section(current_vix, iv_direction, iv_change_pct, today_str, vix_slope)
        else:
            st.caption("VIX data not available")

        # Vanna section
        vanna_result = st.session_state.get('vanna_result')
        if vanna_result:
            render_vanna_section_with_price(
                net_vanna=vanna_result.net_vanna,
                flow_direction=vanna_result.flow_direction.value,
                spot_price=analysis.current_price,
                expiry=expiry,
                iv_direction=iv_direction,
            )
        else:
            st.subheader("Vanna Flow")
            st.caption("Vanna data not available - need delta/vega from API")

        # Charm section
        render_charm_section(analysis, expiry)

        # Delta Flow section
        delta_calc = st.session_state.get('delta_flow_calculator')
        if delta_calc and delta_calc.trade_count > 0:
            render_delta_flow_section(
                cumulative_delta=delta_calc.cumulative_customer_delta,
                spot_price=analysis.current_price,
                flow_direction=delta_calc.get_flow_direction().value,
                trade_count=delta_calc.trade_count,
                expiry=expiry,
            )
        else:
            st.divider()
            st.subheader("Delta Flow - ES Futures Equivalent")
            st.caption("No trade data yet. Delta flow will appear after tick data is processed.")

        # Combined Dealer Hedge section
        st.divider()

        # Calculate ES equivalents for all three sources
        charm_es = 0.0
        if analysis.charm_flow and analysis.charm_flow.net_charm is not None:
            charm_es = calculate_es_futures_equivalent(
                analysis.charm_flow.net_charm,
                analysis.current_price,
            )

        vanna_es = 0.0
        vanna_result = st.session_state.get('vanna_result')
        if vanna_result and vanna_result.net_vanna is not None:
            vanna_es = calculate_es_futures_from_vanna(
                vanna_result.net_vanna,
                analysis.current_price,
                st.session_state.get('iv_direction', 'FLAT'),
            )

        delta_flow_es = 0.0
        if delta_calc:
            delta_flow_es = delta_calc.get_dealer_hedge_es(analysis.current_price)

        # Determine near-expiry flags
        is_charm_max = False
        is_vanna_minimal = False
        if analysis.charm_flow:
            # Check if near expiry (< 2 hours)
            hours_to_expiry = getattr(analysis.charm_flow, 'hours_to_expiry', None)
            if hours_to_expiry is not None and hours_to_expiry < 2:
                is_charm_max = True
                is_vanna_minimal = True

        render_combined_hedge(
            charm_es=charm_es,
            vanna_es=vanna_es,
            delta_flow_es=delta_flow_es,
            is_charm_max=is_charm_max,
            is_vanna_minimal=is_vanna_minimal,
        )

        # AI Prompt
        render_ai_prompt_expander(analysis)

    # ============================================================
    # TIER 4: MARKET STRUCTURE
    # ============================================================
    render_tier4_structure()

    # IV Skew Section
    if not strike_df.empty and (strike_df['call_iv'].notna().any() or strike_df['put_iv'].notna().any()):
        st.subheader("📈 Implied Volatility Skew")

        fig_iv = go.Figure()

        # Plot Call IV
        call_iv_data = strike_df[strike_df['call_iv'].notna()]
        if not call_iv_data.empty:
            fig_iv.add_trace(go.Scatter(
                x=call_iv_data['strike'],
                y=call_iv_data['call_iv'] * 100,  # Convert to percentage
                mode='lines+markers',
                name='Call IV',
                line=dict(color='green', width=2),
                marker=dict(size=6)
            ))

        # Plot Put IV
        put_iv_data = strike_df[strike_df['put_iv'].notna()]
        if not put_iv_data.empty:
            fig_iv.add_trace(go.Scatter(
                x=put_iv_data['strike'],
                y=put_iv_data['put_iv'] * 100,  # Convert to percentage
                mode='lines+markers',
                name='Put IV',
                line=dict(color='red', width=2),
                marker=dict(size=6)
            ))

        # Add vertical line at underlying price
        fig_iv.add_vline(
            x=st.session_state.underlying_price,
            line_dash="dash",
            line_color="orange",
            line_width=2,
            annotation_text=f"${st.session_state.underlying_price:,.2f}",
            annotation_position="top"
        )

        # Format expiration date for display (YYMMDD -> Mon DD, YYYY)
        exp_display = st.session_state.expiration
        try:
            exp_date = datetime.strptime(st.session_state.expiration, "%y%m%d")
            exp_display = exp_date.strftime("%b %d, %Y")
        except:
            pass

        fig_iv.update_layout(
            title=f'{st.session_state.symbol} Implied Volatility Skew - Exp: {exp_display}',
            xaxis_title='Strike Price',
            yaxis_title='Implied Volatility (%)',
            template='plotly_white',
            height=400,
            hovermode='x unified'
        )

        st.plotly_chart(fig_iv, width='stretch')

    st.subheader("📊 Volume & Open Interest")

    if not strike_df.empty:
        # Two columns for OI and Volume charts
        col3, col4 = st.columns(2)

        with col3:
            # Open Interest Chart
            fig_oi = go.Figure()
            fig_oi.add_trace(go.Bar(
                x=strike_df['strike'],
                y=strike_df['call_oi'],
                name='Call OI',
                marker_color='green'
            ))
            fig_oi.add_trace(go.Bar(
                x=strike_df['strike'],
                y=-strike_df['put_oi'],
                name='Put OI',
                marker_color='red'
            ))

            # Add vertical line at underlying price
            fig_oi.add_vline(
                x=st.session_state.underlying_price,
                line_dash="dash",
                line_color="orange",
                line_width=2,
                annotation_text=f"${st.session_state.underlying_price:,.2f}",
                annotation_position="top"
            )

            fig_oi.update_layout(
                title='Open Interest by Strike',
                xaxis_title='Strike',
                yaxis_title='Open Interest',
                barmode='relative',
                template='plotly_white',
                height=400
            )
            st.plotly_chart(fig_oi, width='stretch')

        with col4:
            # Volume Chart with toggle
            volume_view = st.radio(
                "Volume View",
                ["Calls vs Puts", "Total Volume"],
                index=["Calls vs Puts", "Total Volume"].index(st.session_state.volume_view),
                key="volume_view_radio",
                horizontal=True,
                help="Switch between separate call/put volume or total volume by strike"
            )
            st.session_state.volume_view = volume_view

            fig_vol = go.Figure()

            if volume_view == "Calls vs Puts":
                # Separate calls and puts
                fig_vol.add_trace(go.Bar(
                    x=strike_df['strike'],
                    y=strike_df['call_volume'],
                    name='Call Volume',
                    marker_color='lightgreen'
                ))
                fig_vol.add_trace(go.Bar(
                    x=strike_df['strike'],
                    y=-strike_df['put_volume'],
                    name='Put Volume',
                    marker_color='lightcoral'
                ))
                barmode = 'relative'
            else:  # Total Volume
                # Total volume (calls + puts)
                total_volume = strike_df['call_volume'] + strike_df['put_volume']
                fig_vol.add_trace(go.Bar(
                    x=strike_df['strike'],
                    y=total_volume,
                    name='Total Volume',
                    marker_color='purple'
                ))
                barmode = 'group'

            # Add vertical line at underlying price
            fig_vol.add_vline(
                x=st.session_state.underlying_price,
                line_dash="dash",
                line_color="orange",
                line_width=2,
                annotation_text=f"${st.session_state.underlying_price:,.2f}",
                annotation_position="top"
            )

            fig_vol.update_layout(
                title=f'Volume by Strike - {volume_view}',
                xaxis_title='Strike',
                yaxis_title='Volume',
                barmode=barmode,
                template='plotly_white',
                height=400
            )
            st.plotly_chart(fig_vol, width='stretch')

        # Top Strikes Table (with tick data when available)
        render_top_strikes_table(strike_df)

    # Auto-refresh logic - only rerun when it's time to fetch, not constantly
    if st.session_state.auto_refresh and st.session_state.last_fetch_time > 0:
        elapsed = time.time() - st.session_state.last_fetch_time
        # Get refresh interval from session state or default
        refresh_interval = st.session_state.get('refresh_interval', 60)
        time_until_refresh = refresh_interval - elapsed

        if time_until_refresh <= 0:
            # Time to refresh - rerun immediately
            st.rerun()
        else:
            # Schedule rerun for when refresh is due (max 30 seconds to avoid long waits)
            wait_time = min(time_until_refresh, 30)
            time.sleep(wait_time)
            st.rerun()


if __name__ == "__main__":
    main()
