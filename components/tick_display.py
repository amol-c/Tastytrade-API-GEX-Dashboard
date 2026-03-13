"""
Tick Data Display Component

Provides UI elements for displaying real-time OI estimation data:
- OI adjustment indicators
- Buy/sell volume breakdown
- Per-strike flow visualization
- Delta-weighted flow metrics

Single Responsibility: Data formatting and Streamlit rendering for tick data.
"""
import streamlit as st
from typing import Dict, Optional, Tuple, TYPE_CHECKING

from utils.delta_flow_calculator import calculate_delta_weighted_flow, ES_MULTIPLIER

if TYPE_CHECKING:
    from utils.tick_data_manager import TickDataManager


# --- Data Formatting Functions (Pure, Testable) ---


def format_oi_adjustment(raw_oi: int, adjusted_oi: int) -> Dict:
    """
    Format OI adjustment for display.

    Args:
        raw_oi: Original OI from Summary event
        adjusted_oi: Adjusted OI after tick accumulation

    Returns:
        Dict with raw, adjusted, change, change_pct, direction, display
    """
    change = adjusted_oi - raw_oi

    if raw_oi > 0:
        change_pct = (change / raw_oi) * 100
    else:
        change_pct = 0

    if change > 0:
        direction = "up"
        display = f"{raw_oi:,} → {adjusted_oi:,} (+{change:,})"
    elif change < 0:
        direction = "down"
        display = f"{raw_oi:,} → {adjusted_oi:,} ({change:,})"
    else:
        direction = "flat"
        display = f"{adjusted_oi:,}"

    return {
        "raw": raw_oi,
        "adjusted": adjusted_oi,
        "change": change,
        "change_pct": round(change_pct, 1),
        "direction": direction,
        "display": display,
    }


def format_volume_breakdown(
    buy_volume: int,
    sell_volume: int,
    undefined_volume: int,
) -> Dict:
    """
    Format volume breakdown for display.

    Args:
        buy_volume: Buy-initiated volume
        sell_volume: Sell-initiated volume
        undefined_volume: Undefined side volume

    Returns:
        Dict with buy, sell, undefined, net, total, percentages
    """
    total = buy_volume + sell_volume + undefined_volume
    net = buy_volume - sell_volume

    if total > 0:
        buy_pct = round((buy_volume / total) * 100, 1)
        sell_pct = round((sell_volume / total) * 100, 1)
    else:
        buy_pct = 0
        sell_pct = 0

    return {
        "buy": buy_volume,
        "sell": sell_volume,
        "undefined": undefined_volume,
        "net": net,
        "total": total,
        "buy_pct": buy_pct,
        "sell_pct": sell_pct,
    }


def prepare_strike_flow_data(
    option_data: Dict,
    tick_manager: Optional["TickDataManager"],
) -> Dict:
    """
    Prepare per-strike flow data for visualization.

    Args:
        option_data: Dict mapping symbol -> {oi, strike, type, ...}
        tick_manager: TickDataManager with accumulated tick data

    Returns:
        Dict mapping symbol -> flow data
    """
    result = {}

    for symbol, data in option_data.items():
        if tick_manager:
            breakdown = tick_manager.get_volume_breakdown(symbol)
            has_data = (
                breakdown["buy_volume"] > 0 or
                breakdown["sell_volume"] > 0 or
                breakdown["opening_oi"] > 0
            )
        else:
            breakdown = {"buy_volume": 0, "sell_volume": 0, "undefined_volume": 0, "opening_oi": 0}
            has_data = False

        result[symbol] = {
            "strike": data.get("strike"),
            "type": data.get("type"),
            "buy_volume": breakdown["buy_volume"],
            "sell_volume": breakdown["sell_volume"],
            "undefined_volume": breakdown["undefined_volume"],
            "net_flow": breakdown["buy_volume"] - breakdown["sell_volume"],
            "has_tick_data": has_data,
        }

    return result


def get_tick_summary(tick_manager: Optional["TickDataManager"]) -> Dict:
    """
    Get overall tick data summary.

    Args:
        tick_manager: TickDataManager instance

    Returns:
        Summary dict with totals and flow direction
    """
    if tick_manager is None:
        return {
            "symbol_count": 0,
            "total_buy": 0,
            "total_sell": 0,
            "total_undefined": 0,
            "net_flow": 0,
            "flow_direction": "NEUTRAL",
        }

    stats = tick_manager.get_stats()
    net = stats["total_buy_volume"] - stats["total_sell_volume"]

    if net > 0:
        direction = "BUY"
    elif net < 0:
        direction = "SELL"
    else:
        direction = "NEUTRAL"

    return {
        "symbol_count": stats["symbol_count"],
        "total_buy": stats["total_buy_volume"],
        "total_sell": stats["total_sell_volume"],
        "total_undefined": stats["total_undefined_volume"],
        "net_flow": net,
        "flow_direction": direction,
    }


# --- Streamlit Rendering Functions ---


def render_tick_summary(tick_manager: Optional["TickDataManager"]):
    """
    Render tick data summary in sidebar or main area.

    Args:
        tick_manager: TickDataManager instance
    """
    summary = get_tick_summary(tick_manager)

    if summary["symbol_count"] == 0:
        st.caption("No tick data accumulated yet")
        return

    # Flow direction indicator
    direction = summary["flow_direction"]
    if direction == "BUY":
        st.metric(
            "Net Flow",
            f"+{summary['net_flow']:,}",
            delta="Buying pressure",
            delta_color="normal",
        )
    elif direction == "SELL":
        st.metric(
            "Net Flow",
            f"{summary['net_flow']:,}",
            delta="Selling pressure",
            delta_color="inverse",
        )
    else:
        st.metric("Net Flow", "0", delta="Neutral")

    # Volume breakdown
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"🟢 Buy: {summary['total_buy']:,}")
    with col2:
        st.caption(f"🔴 Sell: {summary['total_sell']:,}")


def render_oi_adjustment_badge(raw_oi: int, adjusted_oi: int, compact: bool = True):
    """
    Render OI adjustment as inline badge.

    Args:
        raw_oi: Original OI
        adjusted_oi: Adjusted OI
        compact: If True, show compact format
    """
    info = format_oi_adjustment(raw_oi, adjusted_oi)

    if info["direction"] == "up":
        color = "green"
        arrow = "↑"
    elif info["direction"] == "down":
        color = "red"
        arrow = "↓"
    else:
        color = "gray"
        arrow = ""

    if compact and info["change"] != 0:
        st.markdown(
            f"OI: **{adjusted_oi:,}** "
            f"<span style='color:{color}'>({arrow}{abs(info['change']):,})</span>",
            unsafe_allow_html=True,
        )
    else:
        st.text(info["display"])


def render_volume_bar(buy_volume: int, sell_volume: int, width: int = 100):
    """
    Render a buy/sell volume bar.

    Args:
        buy_volume: Buy-initiated volume
        sell_volume: Sell-initiated volume
        width: Bar width in pixels
    """
    total = buy_volume + sell_volume
    if total == 0:
        st.caption("No volume")
        return

    buy_pct = (buy_volume / total) * 100
    sell_pct = (sell_volume / total) * 100

    st.markdown(
        f"""
        <div style="display:flex; width:{width}px; height:12px; border-radius:3px; overflow:hidden;">
            <div style="width:{buy_pct}%; background:#22c55e;"></div>
            <div style="width:{sell_pct}%; background:#ef4444;"></div>
        </div>
        <div style="font-size:10px; color:#888;">
            🟢 {buy_volume:,} | 🔴 {sell_volume:,}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_tick_data_expander(
    tick_manager: Optional["TickDataManager"],
    greeks_data: Optional[Dict] = None,
):
    """
    Render tick data details in an expander.

    Args:
        tick_manager: TickDataManager instance
        greeks_data: Optional dict mapping symbol -> {delta, ...}
    """
    with st.expander("📊 Real-Time Delta Flow", expanded=False):
        if tick_manager is None:
            st.info("Tick data will accumulate as you fetch data")
            return

        summary = get_tick_summary(tick_manager)

        if summary["symbol_count"] == 0:
            st.info("No tick data accumulated yet. Fetch data to start accumulating.")
            return

        # Check if we can show delta-weighted metrics
        has_greeks = greeks_data is not None and len(greeks_data) > 0

        if has_greeks:
            # Delta-weighted metrics
            tick_data = _extract_tick_data_for_delta(tick_manager)
            delta_bought, delta_sold = calculate_delta_weighted_flow(tick_data, greeks_data)
            net_delta = delta_bought + delta_sold
            es_equivalent = -net_delta / ES_MULTIPLIER  # Dealer hedge

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Symbols", summary["symbol_count"])
            with col2:
                st.metric("Δ Bought", f"{delta_bought:+,.0f}")
            with col3:
                st.metric("Δ Sold", f"{delta_sold:,.0f}")
            with col4:
                direction = "↑" if es_equivalent > 0 else "↓" if es_equivalent < 0 else ""
                st.metric("Dealer Hedge", f"{direction}{abs(es_equivalent):,.0f} ES")

            # Flow direction based on dealer hedge
            if es_equivalent > 100:
                st.success("📈 Dealers BUY pressure - Customers net short delta")
            elif es_equivalent < -100:
                st.warning("📉 Dealers SELL pressure - Customers net long delta")
            else:
                st.info("➡️ Neutral Delta Flow")

            st.caption(
                "Delta Flow = Σ(contracts × delta × 100). "
                "Shows dealer hedge requirement from customer trades."
            )
        else:
            # Fallback to contract-based metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Symbols", summary["symbol_count"])
            with col2:
                st.metric("Buy Vol", f"{summary['total_buy']:,}")
            with col3:
                st.metric("Sell Vol", f"{summary['total_sell']:,}")
            with col4:
                net = summary["net_flow"]
                direction = "↑" if net > 0 else "↓" if net < 0 else ""
                st.metric("Net Flow", f"{direction}{abs(net):,}")

            # Flow direction
            direction = summary["flow_direction"]
            if direction == "BUY":
                st.success("📈 Net Buying Pressure - OI likely increasing")
            elif direction == "SELL":
                st.warning("📉 Net Selling Pressure - OI likely decreasing")
            else:
                st.info("➡️ Neutral Flow")

            st.caption(
                "Note: Contract-based flow (Greeks not available). "
                "Pass Greeks data for delta-weighted metrics."
            )


def _extract_tick_data_for_delta(tick_manager: "TickDataManager") -> Dict[str, Dict]:
    """
    Extract tick data in format needed for delta calculation.

    Returns:
        Dict mapping symbol -> {buy_volume, sell_volume}
    """
    result = {}
    for symbol, data in tick_manager.accumulator.data.items():
        result[symbol] = {
            "buy_volume": data.buy_volume,
            "sell_volume": data.sell_volume,
        }
    return result
