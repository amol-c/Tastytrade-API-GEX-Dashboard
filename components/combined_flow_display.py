"""
Combined Flow Display Component
Shows GEX + VEx combined with IV direction for effective support/resistance.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from typing import Dict


def calculate_combined_flow(
    gex_by_strike: Dict[float, Dict[str, float]],
    vex_by_strike: Dict[float, Dict[str, float]],
    iv_direction: str,
    iv_slope: float = 0.0,
) -> Dict[float, Dict[str, float]]:
    """
    Calculate combined flow strength at each strike.

    Logic:
    - IV Falling (bullish): +GEX + +VEx = Strong Support, -GEX + -VEx = Strong Resistance
    - IV Rising (bearish): +GEX + +VEx = Weak (conflicting), -GEX + -VEx = Weak (conflicting)
    - IV slope intensity (-1 to +1) weights the VEx contribution

    Returns:
        Dict of strike -> {gex, vex, combined_flow, strength, label}
    """
    all_strikes = set(gex_by_strike.keys()) | set(vex_by_strike.keys())
    combined = {}

    # Use absolute slope to weight VEx contribution (0 to 1)
    # Higher slope = stronger VEx effect
    slope_weight = abs(iv_slope) if iv_slope else 0.0

    for strike in all_strikes:
        gex_data = gex_by_strike.get(strike, {})
        vex_data = vex_by_strike.get(strike, {})

        net_gex = gex_data.get('net_gex', 0)
        net_vex = vex_data.get('net_vex', 0)

        # Normalize to comparable scale (sign matters most)
        gex_sign = 1 if net_gex > 0 else -1 if net_gex < 0 else 0
        vex_sign = 1 if net_vex > 0 else -1 if net_vex < 0 else 0

        # Calculate VEx flow direction based on IV direction and slope intensity
        # +VEx + IV falling = BUY, +VEx + IV rising = SELL
        # -VEx + IV falling = SELL, -VEx + IV rising = BUY
        # Slope intensity (0-1) weights how much VEx contributes
        if iv_direction == "FALLING":
            vex_flow = vex_sign * slope_weight  # +VEx = buy, -VEx = sell, weighted by slope
        elif iv_direction == "RISING":
            vex_flow = -vex_sign * slope_weight  # +VEx = sell, -VEx = buy, weighted by slope
        else:
            vex_flow = 0  # Flat IV = neutral vanna

        # GEX flow: +GEX = stabilizing (buy dips/sell rallies), -GEX = destabilizing
        # For support/resistance: +GEX = support, -GEX = resistance
        gex_flow = gex_sign

        # Combined flow: sum of GEX and VEx directional flows
        # Positive = supportive (dealers buy), Negative = resistance (dealers sell)
        combined_flow = gex_flow + vex_flow

        # Strength based on alignment and slope intensity
        # vex_flow is now weighted by slope (-1 to +1 range)
        if gex_flow != 0 and abs(vex_flow) > 0.1:
            # Check if same direction
            if (gex_flow > 0 and vex_flow > 0) or (gex_flow < 0 and vex_flow < 0):
                # Aligned - strength based on slope intensity
                if abs(vex_flow) >= 0.5:
                    strength = "STRONG"
                else:
                    strength = "MODERATE"
            else:
                # Conflicting
                strength = "WEAK"
        elif gex_flow != 0 or abs(vex_flow) > 0.1:
            strength = "MODERATE"
        else:
            strength = "NEUTRAL"

        # Label
        if combined_flow > 0:
            label = f"SUPPORT ({strength})"
        elif combined_flow < 0:
            label = f"RESISTANCE ({strength})"
        else:
            label = "NEUTRAL"

        combined[strike] = {
            'net_gex': net_gex,
            'net_vex': net_vex,
            'gex_flow': gex_flow,
            'vex_flow': vex_flow,
            'combined_flow': combined_flow,
            'strength': strength,
            'label': label,
        }

    return combined


def render_combined_flow_section(
    gex_by_strike: Dict[float, Dict[str, float]],
    vex_by_strike: Dict[float, Dict[str, float]],
    iv_direction: str,
    symbol: str,
    spot_price: float,
    expiry: str,
    iv_slope: float = 0.0,
):
    """
    Render the combined GEX + VEx + IV flow chart.

    Args:
        iv_slope: Normalized VIX slope (-1 to +1) for weighting VEx contribution
    """
    st.header("🎯 Combined Flow (GEX + VEx + IV)")

    if not gex_by_strike and not vex_by_strike:
        st.warning("⚠️ No data available for combined flow")
        return

    # Toggle for using 1-hour IV slope weighting
    use_slope = st.checkbox(
        "Use 1-hour IV Slope",
        value=True,
        help="When enabled, VEx contribution is weighted by IV slope intensity. When disabled, VEx uses full weight if IV is directional."
    )

    # If not using slope, use 1.0 (full weight) when directional, 0 when flat
    effective_slope = iv_slope if use_slope else (1.0 if iv_direction != "FLAT" else 0.0)

    combined = calculate_combined_flow(gex_by_strike, vex_by_strike, iv_direction, effective_slope)

    if not combined:
        st.warning("⚠️ Could not calculate combined flow")
        return

    # Create DataFrame
    df = pd.DataFrame([
        {'strike': strike, **data}
        for strike, data in combined.items()
    ]).sort_values('strike')

    col1, col2 = st.columns([2, 1])

    with col1:
        _render_combined_chart(df, symbol, spot_price, expiry, iv_direction)

    with col2:
        _render_combined_metrics(df, spot_price, iv_direction, effective_slope, use_slope)


def _render_combined_chart(df: pd.DataFrame, symbol: str, spot_price: float, expiry: str, iv_direction: str):
    """Render the combined flow bar chart."""

    # Color based on combined flow and strength
    colors = []
    for _, row in df.iterrows():
        flow = row['combined_flow']
        strength = row['strength']

        if flow > 0:  # Support
            if strength == "STRONG":
                colors.append('rgb(0, 200, 0)')  # Bright green
            elif strength == "MODERATE":
                colors.append('rgb(100, 200, 100)')  # Light green
            else:
                colors.append('rgb(180, 220, 180)')  # Pale green
        elif flow < 0:  # Resistance
            if strength == "STRONG":
                colors.append('rgb(200, 0, 0)')  # Bright red
            elif strength == "MODERATE":
                colors.append('rgb(200, 100, 100)')  # Light red
            else:
                colors.append('rgb(220, 180, 180)')  # Pale red
        else:
            colors.append('rgb(150, 150, 150)')  # Gray for neutral

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df['strike'],
        y=df['combined_flow'],
        name='Combined Flow',
        marker_color=colors,
        hovertemplate=(
            'Strike: %{x}<br>'
            'Flow: %{y}<br>'
            '<extra></extra>'
        )
    ))

    # Add spot price line
    fig.add_vline(
        x=spot_price,
        line_dash="dash",
        line_color="yellow",
        annotation_text=f"Spot: ${spot_price:,.0f}"
    )

    # Add zero line
    fig.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.5)

    # Format expiration
    try:
        exp_date = datetime.strptime(expiry, "%y%m%d")
        exp_display = exp_date.strftime("%b %d, %Y")
    except:
        exp_display = expiry

    iv_label = f"IV {iv_direction}" if iv_direction != "FLAT" else "IV FLAT"

    fig.update_layout(
        title=f'{symbol} Combined Flow - {iv_label} (Exp: {exp_display})',
        xaxis_title='Strike Price',
        yaxis_title='Combined Flow (+ = Support, - = Resistance)',
        template='plotly_white',
        height=400,
        yaxis=dict(
            tickvals=[-2, -1, 0, 1, 2],
            ticktext=['Strong Resist', 'Resist', 'Neutral', 'Support', 'Strong Support']
        )
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_combined_metrics(df: pd.DataFrame, spot_price: float, iv_direction: str, iv_slope: float = 0.0, use_slope: bool = True):
    """Render the combined flow metrics panel."""
    st.subheader("📊 Flow Analysis")

    # IV Direction and Slope indicator
    iv_color = "red" if iv_direction == "RISING" else "green" if iv_direction == "FALLING" else "gray"
    st.markdown(f"**IV Direction:** :{iv_color}[{iv_direction}]")

    if use_slope:
        st.markdown(f"**IV Slope:** `{iv_slope:+.2f}` (VEx weight: {abs(iv_slope)*100:.0f}%)")
    else:
        weight_pct = 100 if iv_direction != "FLAT" else 0
        st.markdown(f"**VEx Weight:** {weight_pct}% (slope disabled)")

    with st.expander("ℹ️ How to interpret"):
        st.markdown("""
**Bar Colors = Dealer Action Intensity**

| Color | Meaning | Dealer Action |
|-------|---------|---------------|
| 🟩 **Bright Green** | Strong Support | Dealers BUY heavily |
| 🟢 Pale Green | Weak Support | Dealers buy lightly |
| 🟥 **Bright Red** | Strong Resistance | Dealers SELL heavily |
| 🔴 Pale Red | Weak Resistance | Dealers sell lightly |
| ⬜ Gray | Neutral | No directional flow |

**When is it STRONG vs WEAK?**
- **STRONG:** GEX and VEx agree (both push same direction)
- **WEAK:** GEX and VEx conflict (cancel each other out)

**How to Trade:**
- Buy dips at **bright green** levels
- Sell rallies at **bright red** levels
- Be cautious at **pale** levels (mixed signals)
""")

    # Find key levels
    df_below = df[df['strike'] < spot_price].copy()
    df_above = df[df['strike'] > spot_price].copy()

    # Strongest support below spot
    if not df_below.empty:
        strong_supports = df_below[df_below['combined_flow'] > 0].nlargest(2, 'combined_flow')
        if not strong_supports.empty:
            st.markdown("**Support Levels:**")
            for _, row in strong_supports.iterrows():
                strength_emoji = "🟢" if row['strength'] == "STRONG" else "🟡"
                st.caption(f"{strength_emoji} ${row['strike']:,.0f} ({row['strength']})")

    # Strongest resistance above spot
    if not df_above.empty:
        strong_resists = df_above[df_above['combined_flow'] < 0].nsmallest(2, 'combined_flow')
        if not strong_resists.empty:
            st.markdown("**Resistance Levels:**")
            for _, row in strong_resists.iterrows():
                strength_emoji = "🔴" if row['strength'] == "STRONG" else "🟠"
                st.caption(f"{strength_emoji} ${row['strike']:,.0f} ({row['strength']})")

    # Conflicting levels (weak)
    weak_levels = df[(df['strength'] == 'WEAK') & (df['combined_flow'] != 0)]
    if not weak_levels.empty:
        st.markdown("**⚠️ Weak/Conflicting:**")
        for _, row in weak_levels.head(3).iterrows():
            st.caption(f"${row['strike']:,.0f} - GEX vs VEx conflict")
