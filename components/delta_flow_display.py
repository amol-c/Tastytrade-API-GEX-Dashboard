"""
Delta Flow Display Component

Displays delta flow ES futures chart and metrics.

Single Responsibility: Render delta flow UI elements.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.delta_flow_history import DeltaFlowHistoryTracker
from utils.delta_flow_calculator import ES_MULTIPLIER


def render_delta_flow_section(
    cumulative_delta: float,
    spot_price: float,
    flow_direction: str,
    trade_count: int,
    expiry: str,
):
    """
    Render delta flow section with ES futures equivalent.

    Matches format of Charm and Vanna sections.

    Args:
        cumulative_delta: Cumulative customer delta
        spot_price: Current underlying price
        flow_direction: "BUY", "SELL", or "NEUTRAL"
        trade_count: Number of trades processed
        expiry: Option expiry in YYMMDD format
    """
    st.divider()
    st.subheader("Delta Flow - ES Futures Equivalent")

    st.caption("ES contracts dealers hedge from customer trades (+ = BUY, - = SELL)")

    with st.expander("ℹ️ What is Delta Flow?"):
        st.markdown("""
**Delta Flow = Cumulative delta from customer trades**

Unlike Charm (time-based) and Vanna (IV-based), Delta Flow measures **actual trading activity**.

**How it works:**
- Customer buys calls (+δ) → dealer shorts calls → dealer **SELLS** to hedge
- Customer buys puts (-δ) → dealer shorts puts → dealer **BUYS** to hedge
- Customer sells calls → dealer longs calls → dealer **BUYS** to hedge
- Customer sells puts → dealer longs puts → dealer **SELLS** to hedge

**Formula:** `ES = -Customer Delta / 50`

**Key Advantage:** Remains reliable near expiry (trade-based, no √T formula issues).

*Shows real-time hedging pressure from trades, not theoretical Greeks.*
""")

    # Calculate ES equivalent
    es_equivalent = -cumulative_delta / ES_MULTIPLIER if cumulative_delta != 0 else 0

    # Metrics - 3 columns matching charm/vanna
    col1, col2, col3 = st.columns(3)

    with col1:
        es_sign = "+" if es_equivalent >= 0 else ""
        st.metric(
            "ES Futures to Hedge",
            f"{es_sign}{es_equivalent:,.0f} contracts",
        )
    with col2:
        st.metric("Flow Direction", flow_direction)
    with col3:
        st.metric("Trades Processed", f"{trade_count:,}")

    # Chart
    _render_delta_flow_chart(es_equivalent, expiry)


def _render_delta_flow_chart(current_es: float, expiry: str, limit: int = 50):
    """Render cumulative ES contracts over time chart."""
    tracker = DeltaFlowHistoryTracker(expiry=expiry)
    history = tracker.get_es_futures_series(limit=limit)

    if len(history) < 2:
        st.caption("Chart will appear after multiple data points")
        return

    st.caption("Cumulative ES Hedge Over Time")
    hist_df = pd.DataFrame(history)
    hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'])

    # Color based on current value
    if current_es != 0:
        last_es = current_es
    else:
        last_es = hist_df['es_futures'].iloc[-1]

    line_color = 'green' if last_es >= 0 else 'red'
    fill_color = 'rgba(0,255,0,0.1)' if last_es >= 0 else 'rgba(255,0,0,0.1)'

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_df['timestamp'],
        y=hist_df['es_futures'],
        mode='lines+markers',
        name='ES Contracts',
        line=dict(color=line_color, width=2),
        fill='tozeroy',
        fillcolor=fill_color
    ))

    # Zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

    fig.update_layout(
        height=250,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_title="Time",
        yaxis_title="ES Contracts",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)


def render_delta_flow_metric_only(
    cumulative_delta: float,
    flow_direction: str,
):
    """
    Render just the delta flow metric (for Market Summary row).

    Args:
        cumulative_delta: Cumulative customer delta
        flow_direction: "BUY", "SELL", or "NEUTRAL"
    """
    es_equivalent = -cumulative_delta / ES_MULTIPLIER if cumulative_delta != 0 else 0

    st.metric(
        "Delta Flow",
        flow_direction,
        delta=f"{es_equivalent:+,.0f} ES",
        delta_color="normal" if flow_direction == "BUY" else "inverse" if flow_direction == "SELL" else "off"
    )
