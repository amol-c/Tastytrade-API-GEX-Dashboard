"""
Market Analysis Display Component
Displays market bias, confidence, and Greek flows with help information.
"""
import streamlit as st


def render_bias_help_expander():
    """Render the help expander explaining how bias is calculated."""
    with st.expander("ℹ️ How is this calculated?"):
        st.markdown("""
**Bias Score (0-100)** starts at 50 (neutral) and adds/subtracts points:

| Factor | Max Points | How It Works |
|--------|------------|--------------|
| **Vanna + Charm Flow** | ±20 | Time-weighted: Morning favors Vanna, Afternoon favors Charm |
| **Dealer Stance** | ±15 | Based on Call GEX / Total GEX ratio |
| **Customer Sentiment** | ±10 | Based on Call Volume / Total Volume |
| **Price vs Gamma Flip** | ±5 | Above flip = bullish, Below = bearish |

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


def render_market_analysis_header(analysis):
    """
    Render the market analysis metrics row.

    Args:
        analysis: MarketAnalysis object
    """
    bias_emoji = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '🟡'}
    conf_emoji = {'HIGH': '🔥', 'MEDIUM': '⚡', 'LOW': '💤'}

    # Check if vanna_flow exists (for backwards compatibility)
    has_vanna = hasattr(analysis, 'vanna_flow') and analysis.vanna_flow is not None

    if has_vanna:
        bias_col1, bias_col2, bias_col3, bias_col4 = st.columns(4)
    else:
        bias_col1, bias_col2, bias_col3 = st.columns(3)

    with bias_col1:
        st.metric(
            "Market Bias",
            f"{bias_emoji.get(analysis.bias, '')} {analysis.bias}",
            delta=f"Score: {analysis.bias_score:.0f}/100",
            delta_color="normal" if analysis.bias == 'BULLISH' else "inverse" if analysis.bias == 'BEARISH' else "off"
        )

    with bias_col2:
        st.metric(
            "Confidence",
            f"{conf_emoji.get(analysis.confidence, '')} {analysis.confidence}"
        )

    if has_vanna:
        with bias_col3:
            st.metric(
                "Vanna Flow",
                analysis.vanna_flow.direction,
                delta=f"IV {analysis.vanna_flow.iv_direction}",
                delta_color="normal" if analysis.vanna_flow.direction == 'BUY' else "inverse" if analysis.vanna_flow.direction == 'SELL' else "off"
            )
        with bias_col4:
            st.metric(
                "Charm Flow",
                analysis.charm_flow.direction,
                delta="UP pressure" if analysis.charm_flow.direction == 'BUY' else "DOWN pressure" if analysis.charm_flow.direction == 'SELL' else "Neutral",
                delta_color="normal" if analysis.charm_flow.direction == 'BUY' else "inverse" if analysis.charm_flow.direction == 'SELL' else "off"
            )
    else:
        with bias_col3:
            st.metric(
                "Charm Flow",
                analysis.charm_flow.direction,
                delta="UP pressure" if analysis.charm_flow.direction == 'BUY' else "DOWN pressure" if analysis.charm_flow.direction == 'SELL' else "Neutral",
                delta_color="normal" if analysis.charm_flow.direction == 'BUY' else "inverse" if analysis.charm_flow.direction == 'SELL' else "off"
            )
