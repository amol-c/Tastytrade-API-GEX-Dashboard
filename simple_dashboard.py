"""
Simple GEX Dashboard - Direct WebSocket approach (no background threads)
Fetches data once when you click "Fetch Data", then displays it
Works on weekends with Friday's closing data
"""
import streamlit as st
import json
import time
import logging
from datetime import datetime, timedelta

import os
os.makedirs('logs', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/dashboard.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
import pandas as pd
import plotly.graph_objects as go
from utils.tradier_api import get_underlying_price as tradier_get_underlying, fetch_option_data as tradier_fetch_options
from utils.websocket_manager import connect_websocket as dxfeed_connect, fetch_option_data as dxfeed_fetch_options, get_underlying_price as dxfeed_get_underlying
from utils.auth import ensure_streamer_token

from utils.gex_calculator import GEXCalculator
from utils.sentiment_calculator import SentimentCalculator
from utils.market_analyzer import MarketAnalyzer
from utils.charm_history import CharmHistoryTracker, calculate_es_futures_equivalent
from utils.vix_tracker import get_vix_price, determine_iv_direction, calculate_vix_slope, VIXHistoryTracker, VIXSlope
from utils.vanna_calculator import VannaCalculator
from utils.vanna_history import VannaHistoryTracker, calculate_es_futures_from_vanna
from components.charm_display import render_charm_section
from components.vix_display import render_vix_section
from components.vanna_display import render_vanna_section_with_price
from components.greek_dominance import render_greek_dominance_timer
from components.market_analysis_display import render_bias_help_expander, render_market_analysis_header
from components.vex_display import render_vex_section
from components.combined_flow_display import render_combined_flow_section
from components.dashboard_layout import (
    render_tier1_summary,
    render_tier2_exposure,
    render_tier3_flows,
    render_tier4_structure,
    render_key_levels_expander,
    render_ai_prompt_expander,
)

st.set_page_config(page_title="GEX Dashboard", page_icon="📊", layout="wide")

# Preset symbol configuration
PRESET_SYMBOLS = {
    "SPX": {"option_prefix": "SPXW", "default_price": 6000, "increment": 5},
    "NDX": {"option_prefix": "NDXP", "default_price": 20000, "increment": 25},
    "SPY": {"option_prefix": "SPY", "default_price": 680, "increment": 1},
    "QQQ": {"option_prefix": "QQQ", "default_price": 612, "increment": 1},
    "IWM": {"option_prefix": "IWM", "default_price": 240, "increment": 1},
    "DIA": {"option_prefix": "DIA", "default_price": 450, "increment": 1},
}






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


def aggregate_by_strike(option_data):
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
                'put_iv': None
            }

        # Convert to numbers (might be strings from WebSocket or NaN)
        import math

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

    # Convert to DataFrame
    rows = []
    for strike, data in strike_data.items():
        rows.append({
            'strike': strike,
            'call_oi': data['call_oi'],
            'put_oi': data['put_oi'],
            'call_volume': data['call_volume'],
            'put_volume': data['put_volume'],
            'total_oi': data['call_oi'] + data['put_oi'],
            'total_volume': data['call_volume'] + data['put_volume'],
            'call_iv': data['call_iv'],
            'put_iv': data['put_iv']
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('strike').reset_index(drop=True)
    return df


def main():
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

        st.divider()
        st.subheader("🔌 Data Provider")
        provider = st.radio("Select Source", ["Tradier API (REST)", "Tastytrade (dxFeed WebSocket)"], help="Choose your API backend")
        st.divider()
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
        fetch_triggered = st.button("🔄 Fetch Data", type="primary", width='stretch')

        # Auto-fetch logic
        if st.session_state.auto_refresh:
            current_time = time.time()
            if current_time - st.session_state.last_fetch_time >= refresh_interval:
                fetch_triggered = True

        if fetch_triggered:
            with st.spinner(f"Fetching {symbol} data..."):
                try:
                    # Route based on Provider
                    if provider == "Tradier API (REST)":
                        st.info(f"📊 Getting {symbol} price via Tradier...")
                        price = tradier_get_underlying(symbol)
                        
                        if not price:
                            price = default_price
                            st.warning(f"⚠️ Using fallback price: ${price}")
                        else:
                            st.success(f"✅ {symbol} Price: ${price:,.2f}")
                            
                        st.info(f"📡 Fetching option chain via Tradier...")
                        raw_option_data = tradier_fetch_options(symbol, expiration)
                        current_vix = get_vix_price()
                        
                    else:
                        # Tastytrade / dxFeed Flow
                        streamer_token = ensure_streamer_token()
                        if not streamer_token:
                            st.error("Failed to authenticate with Tastytrade. Check .env config.")
                            st.stop()
                            
                        ws = dxfeed_connect(streamer_token)
                        if not ws:
                            st.error("Failed to connect to dxFeed WebSocket.")
                            st.stop()
                            
                        st.info(f"📊 Getting {symbol} price via dxFeed...")
                        price = dxfeed_get_underlying(ws, symbol)
                        
                        if not price:
                            price = default_price
                            st.warning(f"⚠️ Using fallback price: ${price}")
                        else:
                            st.success(f"✅ {symbol} Price: ${price:,.2f}")
                            
                        # Generate option symbols (Old behavior required specific symbols)
                        center_strike = round(price / increment) * increment
                        strikes = []
                        for i in range(-strikes_down, strikes_up + 1):
                            strikes.append(center_strike + (i * increment))
                            
                        option_symbols = []
                        for strike in strikes:
                            if strike == int(strike):
                                strike_str = str(int(strike))
                            else:
                                strike_str = str(strike)
                            option_symbols.append(f".{option_prefix}{expiration}C{strike_str}")
                            option_symbols.append(f".{option_prefix}{expiration}P{strike_str}")
                            
                        st.info(f"📡 Fetching options via dxFeed...")
                        raw_option_data = dxfeed_fetch_options(ws, option_symbols, wait_seconds=15)
                        current_vix = get_vix_price(ws)
                        ws.close()

                    
                    # Filter option_data by strike
                    center_strike = round(price / increment) * increment
                    lower_bound = center_strike - (strikes_down * increment)
                    upper_bound = center_strike + (strikes_up * increment)
                    
                    from utils.gex_calculator import parse_option_symbol
                    option_data = {}
                    for sym, data in raw_option_data.items():
                        parsed = parse_option_symbol(sym)
                        if parsed and lower_bound <= parsed['strike'] <= upper_bound:
                            option_data[sym] = data

                    # VIX already fetched in routing block

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

                    greeks_count = sum(1 for d in option_data.values() if "gamma" in d)
                    oi_count = sum(1 for d in option_data.values() if "oi" in d)
                    volume_count = sum(1 for d in option_data.values() if "volume" in d)

                    st.success(f"✅ Data fetched! Greeks: {greeks_count}, OI: {oi_count}")
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Error: {e}")
                    import traceback
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
        render_key_levels_expander(analysis)

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
            key="gex_view",
            horizontal=True,
            help="Calls vs Puts: Separate bars | Net GEX: Call-Put | Absolute GEX: |Net| magnitude"
        )

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
            annotation_text=f"${st.session_state.underlying_price:,.2f} (Spot)",
            annotation_position="top left",
            annotation_font=dict(color="orange", weight="bold", size=11),
            annotation_bgcolor="rgba(0,0,0,0.8)",
            annotation_borderpad=3
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
                annotation_position="bottom right",
                annotation_font=dict(color="violet", weight="bold", size=11),
                annotation_bgcolor="rgba(0,0,0,0.8)",
                annotation_borderpad=3
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

        st.plotly_chart(fig, use_container_width=True)

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
    if not strike_vex:
        # Diagnostic help
        raw_count = len(st.session_state.option_data) if 'option_data' in st.session_state else 0
        tte = vanna_calc.calculate_tte_from_expiry(st.session_state.expiration)
        with st.expander("🔍 VEx Diagnostic (Hidden)"):
            st.write(f"Raw option data count: {raw_count}")
            if raw_count > 0:
                sample_opt = list(st.session_state.option_data.values())[0]
                st.write(f"Sample Greek values: Δ={sample_opt.get('delta')}, V={sample_opt.get('vega')}, γ={sample_opt.get('gamma')}, OI={sample_opt.get('oi')}")
            st.write(f"Expiration string: {st.session_state.expiration}")
            st.write(f"Calculated TTE (years): {tte:.6f}")
            st.write(f"Spot price: {st.session_state.underlying_price}")

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
    strike_df = aggregate_by_strike(st.session_state.option_data)

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
            annotation_text=f"${st.session_state.underlying_price:,.2f} (Spot)",
            annotation_position="top left",
            annotation_font=dict(color="orange", weight="bold", size=11),
            annotation_bgcolor="rgba(0,0,0,0.8)",
            annotation_borderpad=3
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

        st.plotly_chart(fig_iv, use_container_width=True)

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
            st.plotly_chart(fig_oi, use_container_width=True)

        with col4:
            # Volume Chart with toggle
            volume_view = st.radio(
                "Volume View",
                ["Calls vs Puts", "Total Volume"],
                key="volume_view",
                horizontal=True,
                help="Switch between separate call/put volume or total volume by strike"
            )

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
            st.plotly_chart(fig_vol, use_container_width=True)

        # Top Strikes Table
        st.subheader("🔝 Top Strikes")

        # Create tabs for different views
        tab1, tab2, tab3 = st.tabs(["By Total OI", "By Total Volume", "By Put/Call Ratio"])

        with tab1:
            top_oi = strike_df.nlargest(10, 'total_oi')[['strike', 'call_oi', 'put_oi', 'total_oi']]
            top_oi['strike'] = top_oi['strike'].apply(lambda x: f"${x:,.0f}")
            top_oi.columns = ['Strike', 'Call OI', 'Put OI', 'Total OI']
            st.dataframe(top_oi, hide_index=True, width='stretch')

        with tab2:
            top_vol = strike_df.nlargest(10, 'total_volume')[['strike', 'call_volume', 'put_volume', 'total_volume']]
            top_vol['strike'] = top_vol['strike'].apply(lambda x: f"${x:,.0f}")
            top_vol.columns = ['Strike', 'Call Vol', 'Put Vol', 'Total Vol']
            st.dataframe(top_vol, hide_index=True, width='stretch')

        with tab3:
            # Calculate put/call ratio
            pc_ratio_df = strike_df.copy()
            pc_ratio_df['pc_ratio_oi'] = pc_ratio_df['put_oi'] / pc_ratio_df['call_oi'].replace(0, 1)
            pc_ratio_df['pc_ratio_vol'] = pc_ratio_df['put_volume'] / pc_ratio_df['call_volume'].replace(0, 1)
            top_pc = pc_ratio_df.nlargest(10, 'pc_ratio_oi')[['strike', 'pc_ratio_oi', 'pc_ratio_vol', 'total_oi']]
            top_pc['strike'] = top_pc['strike'].apply(lambda x: f"${x:,.0f}")
            top_pc['pc_ratio_oi'] = top_pc['pc_ratio_oi'].apply(lambda x: f"{x:.2f}")
            top_pc['pc_ratio_vol'] = top_pc['pc_ratio_vol'].apply(lambda x: f"{x:.2f}")
            top_pc.columns = ['Strike', 'P/C Ratio (OI)', 'P/C Ratio (Vol)', 'Total OI']
            st.dataframe(top_pc, hide_index=True, width='stretch')

    # Sentiment Ratios
    st.subheader("📊 Sentiment Ratios")

    sentiment_calc = SentimentCalculator()
    ratio_col1, ratio_col2 = st.columns(2)

    with ratio_col1:
        dealer_result = sentiment_calc.calculate_from_gex_metrics(metrics)
        st.metric(
            "Dealer Gamma Ratio",
            f"{dealer_result.ratio:.2f}",
            delta=dealer_result.label,
            delta_color="normal" if dealer_result.ratio >= 0.5 else "inverse",
            help="Call GEX / Total GEX. 1.0 = stabilizing, 0.0 = destabilizing, 0.5 = neutral."
        )
        st.progress(dealer_result.ratio)

    with ratio_col2:
        sentiment_result = sentiment_calc.calculate_from_strike_df(strike_df)
        if sentiment_result:
            st.metric(
                "Active Sentiment (Customers)",
                f"{sentiment_result.ratio:.2f}",
                delta=sentiment_result.label,
                delta_color="normal" if sentiment_result.ratio >= 0.5 else "inverse",
                help="Call Volume / Total Volume. 1.0 = bullish, 0.0 = bearish, 0.5 = neutral."
            )
            st.progress(sentiment_result.ratio)
        else:
            st.metric("Active Sentiment", "N/A", help="No volume data available")

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
