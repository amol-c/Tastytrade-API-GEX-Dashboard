"""
Market Analysis Display Component
Displays market bias, confidence, and Greek flows with help information.
"""
import streamlit as st
from typing import Optional

from utils.delta_flow_calculator import DeltaFlowCalculator, ES_MULTIPLIER


def render_bias_help_expander():
    """Render the help expander explaining how bias is calculated."""
    with st.expander("ℹ️ How is this calculated?"):
        st.markdown("""
**Bias Score (0-100)** starts at 50 (neutral) and adds/subtracts points:

| Factor | Max Points | How It Works |
|--------|------------|--------------|
| **Vanna + Charm Flow** | ±20 | Time-weighted: Morning favors Vanna, Afternoon favors Charm |
| **Delta Flow** | ±10 | Real-time customer trading activity |
| **Dealer Stance** | ±15 | Based on Call GEX / Total GEX ratio |
| **Customer Sentiment** | ±10 | Based on Call Volume / Total Volume |
| **Price vs Gamma Flip** | ±5 | Above flip = bullish, Below = bearish |

---

**Three Sources of Dealer Hedging:**

| Source | What Changes Delta | Near Expiry | Data |
|--------|-------------------|-------------|------|
| **Charm** | Time passing (∂Δ/∂t) | MAX | Greeks |
| **Vanna** | IV changes (∂Δ/∂σ) | MINIMAL | Greeks + VIX |
| **Delta Flow** | Customer trades | NORMAL | Tick data |

*Combined Dealer Hedge = Charm ES + Vanna ES + Delta Flow ES*

---

**Time-Based Greek Weighting:**
- **>5h to expiry:** Vanna 70% / Charm 30%
- **3-5h:** Vanna 50% / Charm 50%
- **1-3h:** Vanna 30% / Charm 70%
- **<1h:** Vanna 10% / Charm 90%

**Confidence Levels:**
- **HIGH:** Score ≥80 (bullish) or ≤20 (bearish)
- **MEDIUM:** Score 70-79 or 21-30
- **LOW:** Score 65-69, 31-35, or near 50
""")


def render_market_analysis_header(
    analysis,
    delta_flow_calculator: Optional[DeltaFlowCalculator] = None,
):
    """
    Render the market analysis metrics row.

    Args:
        analysis: MarketAnalysis object
        delta_flow_calculator: Optional DeltaFlowCalculator with accumulated data
    """
    bias_emoji = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '🟡'}
    conf_emoji = {'HIGH': '🔥', 'MEDIUM': '⚡', 'LOW': '💤'}

    # Check if vanna_flow exists (for backwards compatibility)
    has_vanna = hasattr(analysis, 'vanna_flow') and analysis.vanna_flow is not None
    has_delta_flow = delta_flow_calculator is not None

    # Determine number of columns
    if has_vanna and has_delta_flow:
        cols = st.columns(5)
    elif has_vanna or has_delta_flow:
        cols = st.columns(4)
    else:
        cols = st.columns(3)

    col_idx = 0

    # Column 1: Market Bias
    with cols[col_idx]:
        st.metric(
            "Market Bias",
            f"{bias_emoji.get(analysis.bias, '')} {analysis.bias}",
            delta=f"Score: {analysis.bias_score:.0f}/100",
            delta_color="normal" if analysis.bias == 'BULLISH' else "inverse" if analysis.bias == 'BEARISH' else "off"
        )
    col_idx += 1

    # Column 2: Confidence
    with cols[col_idx]:
        st.metric(
            "Confidence",
            f"{conf_emoji.get(analysis.confidence, '')} {analysis.confidence}"
        )
    col_idx += 1

    # Column 3: Vanna Flow (if available)
    if has_vanna:
        with cols[col_idx]:
            st.metric(
                "Vanna Flow",
                analysis.vanna_flow.direction,
                delta=f"IV {analysis.vanna_flow.iv_direction}",
                delta_color="normal" if analysis.vanna_flow.direction == 'BUY' else "inverse" if analysis.vanna_flow.direction == 'SELL' else "off"
            )
        col_idx += 1

    # Column 4: Charm Flow
    with cols[col_idx]:
        st.metric(
            "Charm Flow",
            analysis.charm_flow.direction,
            delta="UP pressure" if analysis.charm_flow.direction == 'BUY' else "DOWN pressure" if analysis.charm_flow.direction == 'SELL' else "Neutral",
            delta_color="normal" if analysis.charm_flow.direction == 'BUY' else "inverse" if analysis.charm_flow.direction == 'SELL' else "off"
        )
    col_idx += 1

    # Column 5: Delta Flow (if available)
    if has_delta_flow:
        with cols[col_idx]:
            flow_dir = delta_flow_calculator.get_flow_direction().value
            es_equiv = delta_flow_calculator.get_dealer_hedge_es(analysis.current_price)
            st.metric(
                "Delta Flow",
                flow_dir,
                delta=f"{es_equiv:+,.0f} ES",
                delta_color="normal" if flow_dir == 'BUY' else "inverse" if flow_dir == 'SELL' else "off"
            )
