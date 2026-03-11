"""
VEx (Vanna Exposure) Display Component
Displays VEx chart by strike and metrics panel.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from typing import Dict


def render_vex_section(
    strike_vex: Dict[float, Dict[str, float]],
    vex_metrics: Dict[str, float],
    symbol: str,
    spot_price: float,
    expiry: str,
):
    """
    Render the VEx section with chart and metrics.

    Args:
        strike_vex: Dict of strike -> {call_vex, put_vex, net_vex}
        vex_metrics: Dict with total_call_vex, total_put_vex, net_vex, max_vex_strike
        symbol: Underlying symbol
        spot_price: Current spot price
        expiry: Expiration in YYMMDD format
    """
    st.header("📊 VEx (Vanna Exposure)")

    if not strike_vex:
        st.warning("⚠️ VEx data not available - need delta/vega from API")
        return

    vex_df = pd.DataFrame([
        {'strike': strike, **data}
        for strike, data in strike_vex.items()
    ]).sort_values('strike')

    col1, col2 = st.columns([2, 1])

    with col1:
        _render_vex_chart(vex_df, symbol, spot_price, expiry)

    with col2:
        _render_vex_metrics(vex_metrics)


def _render_vex_chart(vex_df: pd.DataFrame, symbol: str, spot_price: float, expiry: str):
    """Render the VEx bar chart."""
    if 'vex_view' not in st.session_state:
        st.session_state.vex_view = "Calls vs Puts"

    vex_view = st.radio(
        "VEx View",
        ["Calls vs Puts", "Net VEx"],
        index=["Calls vs Puts", "Net VEx"].index(st.session_state.vex_view),
        key="vex_view_radio",
        horizontal=True,
        help="Calls vs Puts: Separate bars | Net VEx: Combined"
    )
    st.session_state.vex_view = vex_view

    fig = go.Figure()

    if vex_view == "Calls vs Puts":
        fig.add_trace(go.Bar(
            x=vex_df['strike'],
            y=vex_df['call_vex'],
            name='Call VEx',
            marker_color='green'
        ))
        fig.add_trace(go.Bar(
            x=vex_df['strike'],
            y=vex_df['put_vex'],
            name='Put VEx',
            marker_color='red'
        ))
        barmode = 'relative'
        yaxis_title = 'Vanna Exposure ($)'
    else:
        colors = ['green' if x >= 0 else 'red' for x in vex_df['net_vex']]
        fig.add_trace(go.Bar(
            x=vex_df['strike'],
            y=vex_df['net_vex'],
            name='Net VEx',
            marker_color=colors
        ))
        barmode = 'group'
        yaxis_title = 'Net VEx ($)'

    # Add spot price line
    fig.add_vline(
        x=spot_price,
        line_dash="dash",
        line_color="yellow",
        annotation_text=f"Spot: ${spot_price:,.0f}"
    )

    # Add zero line
    fig.add_hline(y=0, line_dash="solid", line_color="gray", opacity=0.5)

    # Format expiration
    try:
        exp_date = datetime.strptime(expiry, "%y%m%d")
        exp_display = exp_date.strftime("%b %d, %Y")
    except:
        exp_display = expiry

    fig.update_layout(
        title=f'{symbol} Vanna Exposure by Strike - {vex_view} (Exp: {exp_display})',
        xaxis_title='Strike Price',
        yaxis_title=yaxis_title,
        barmode=barmode,
        template='plotly_white',
        height=400
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_vex_metrics(vex_metrics: Dict[str, float]):
    """Render the VEx metrics panel."""
    st.subheader("📈 Dealer VEx")

    with st.expander("ℹ️ What is VEx?"):
        st.markdown("""
**VEx = Vanna Exposure**

`VEx = Σ (Vanna × OI × 100 × Spot)`

Measures how IV changes affect dealer delta hedging.

**Flow (with IV direction):**
- Positive VEx + IV↑ → SELL
- Positive VEx + IV↓ → BUY
- Negative VEx + IV↑ → BUY
- Negative VEx + IV↓ → SELL
""")

    st.metric(
        "Call VEx",
        f"${vex_metrics.get('total_call_vex', 0):,.0f}",
        help="Vanna exposure from call options"
    )
    st.metric(
        "Put VEx",
        f"${vex_metrics.get('total_put_vex', 0):,.0f}",
        help="Vanna exposure from put options"
    )
    st.metric(
        "Net VEx",
        f"${vex_metrics.get('net_vex', 0):,.0f}",
        help="Total vanna exposure (calls + puts)"
    )

    if vex_metrics.get('max_vex_strike'):
        st.divider()
        st.metric(
            "Max VEx Strike",
            f"${vex_metrics['max_vex_strike']:,.0f}",
            help="Strike with highest absolute vanna exposure"
        )
