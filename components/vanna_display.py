"""
Vanna Display Component
Displays Vanna ES futures chart and metrics.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.vanna_history import VannaHistoryTracker, calculate_es_futures_from_vanna


def render_vanna_section(analysis, expiry: str, iv_direction: str):
    """
    Render the vanna section with ES futures equivalent.

    Args:
        analysis: VannaProjection object or None
        expiry: Option expiry in YYMMDD format
        iv_direction: "RISING", "FALLING", or "FLAT"
    """
    st.subheader("Vanna Flow")

    has_current_data = analysis is not None and analysis.net_vanna is not None

    if has_current_data:
        iv_rising = (iv_direction == "RISING")
        current_es = calculate_es_futures_from_vanna(
            analysis.net_vanna,
            6000,  # Will be passed from dashboard
            iv_rising
        )
        _render_current_metrics(analysis, current_es, iv_direction)
    else:
        current_es = None
        st.warning("⚠️ Vanna unavailable - insufficient Greeks data")

    # Always show chart if history exists
    _render_vanna_chart(current_es, expiry)


def render_vanna_section_with_price(net_vanna: float, flow_direction: str, spot_price: float, expiry: str, iv_direction: str):
    """
    Render vanna section with spot price for ES calculation.

    Args:
        net_vanna: Net vanna exposure in dollars
        flow_direction: "BUY", "SELL", or "NEUTRAL"
        spot_price: Current underlying price
        expiry: Option expiry in YYMMDD format
        iv_direction: "RISING", "FALLING", or "FLAT"
    """
    st.divider()
    st.subheader("Vanna Flow - ES Futures Equivalent")

    st.caption("ES contracts dealers will trade due to IV changes (+ = BUY, - = SELL)")

    with st.expander("ℹ️ What is VEx (Vanna Exposure)?"):
        st.markdown("""
**VEx = Σ (Vanna × OI × 100 × Spot)**

Vanna measures delta sensitivity to IV changes. VEx aggregates this across all strikes.

**Flow depends on BOTH VEx sign AND IV direction:**
- **Positive VEx + IV rising** → dealers **SELL** (bearish)
- **Positive VEx + IV falling** → dealers **BUY** (bullish)
- **Negative VEx + IV rising** → dealers **BUY** (bullish)
- **Negative VEx + IV falling** → dealers **SELL** (bearish)

*Based on SpotGamma dealer positioning: dealers long calls, short puts.*
""")

    if net_vanna is None:
        st.warning("⚠️ Vanna unavailable - insufficient Greeks data (showing historical data)")
        _render_vanna_chart(None, expiry)
        return

    iv_rising = (iv_direction == "RISING")
    current_es = calculate_es_futures_from_vanna(net_vanna, spot_price, iv_rising)

    # Metrics - matching charm display format
    col1, col2, col3 = st.columns(3)

    with col1:
        es_sign = "+" if current_es >= 0 else "-"
        st.metric(
            "ES Futures to Neutralize",
            f"{es_sign}{abs(current_es):,.0f} contracts",
        )
    with col2:
        st.metric("Flow Direction", flow_direction)
    with col3:
        st.metric("VEx", f"${net_vanna:,.0f}")

    _render_vanna_chart(current_es, expiry)


def _render_current_metrics(analysis, current_es, iv_direction):
    """Render current vanna metrics."""
    col1, col2, col3 = st.columns(3)

    with col1:
        es_sign = "+" if current_es >= 0 else ""
        st.metric(
            "ES Futures",
            f"{es_sign}{current_es:,.0f}",
        )
    with col2:
        st.metric("Flow", analysis.flow_direction.value)
    with col3:
        st.metric("Net Vanna", f"${analysis.net_vanna:,.0f}")

    st.caption(f"IV {iv_direction} → {analysis.flow_direction.value}")


def _render_vanna_chart(current_es, expiry: str, limit: int = 50):
    """Render Vanna ES contracts over time chart."""
    tracker = VannaHistoryTracker(expiry=expiry)
    history = tracker.get_es_futures_series(limit=limit)

    if len(history) < 2:
        st.caption("Chart will appear after multiple data fetches")
        return

    st.caption("ES Contracts Over Time")
    hist_df = pd.DataFrame(history)
    hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'], utc=True)

    # Color based on current or last ES value
    if current_es is not None:
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

    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

    fig.update_layout(
        height=250,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_title="Time",
        yaxis_title="ES Contracts",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)
