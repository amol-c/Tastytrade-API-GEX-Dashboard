"""
Combined Dealer Hedge Display Component

Shows the total dealer hedge from all three sources:
- Charm (time decay)
- Vanna (IV changes)
- Delta Flow (customer trades)

Single Responsibility: Render combined hedge visualization.
"""
import streamlit as st
import plotly.graph_objects as go
from typing import Optional


def render_combined_hedge(
    charm_es: float,
    vanna_es: float,
    delta_flow_es: float,
    is_charm_max: bool = False,
    is_vanna_minimal: bool = False,
):
    """
    Render combined dealer hedge from all three sources.

    Args:
        charm_es: Charm ES equivalent (+ = BUY, - = SELL)
        vanna_es: Vanna ES equivalent (+ = BUY, - = SELL)
        delta_flow_es: Delta Flow ES equivalent (+ = BUY, - = SELL)
        is_charm_max: True if near expiry (charm unreliable)
        is_vanna_minimal: True if near expiry (vanna ~0)
    """
    st.subheader("Combined Dealer Hedge")

    # Calculate total (exclude unreliable values)
    effective_charm = 0 if is_charm_max else charm_es
    effective_vanna = 0 if is_vanna_minimal else vanna_es
    total = effective_charm + effective_vanna + delta_flow_es

    # Direction
    if total > 50:
        direction = "BUY"
        color = "🟢"
        delta_color = "normal"
    elif total < -50:
        direction = "SELL"
        color = "🔴"
        delta_color = "inverse"
    else:
        direction = "NEUTRAL"
        color = "🟡"
        delta_color = "off"

    # Main metrics row
    col1, col2 = st.columns([1, 2])

    with col1:
        st.metric(
            "Net Hedge",
            f"{color} {total:+,.0f} ES",
            delta=direction,
            delta_color=delta_color,
        )

    with col2:
        # Breakdown text
        parts = []
        if is_charm_max:
            parts.append("Charm: MAX")
        else:
            parts.append(f"Charm: {charm_es:+,.0f}")

        if is_vanna_minimal:
            parts.append("Vanna: ~0")
        else:
            parts.append(f"Vanna: {vanna_es:+,.0f}")

        parts.append(f"Delta: {delta_flow_es:+,.0f}")

        st.caption("Breakdown: " + " | ".join(parts))

        # Visual bar
        _render_hedge_bar(effective_charm, effective_vanna, delta_flow_es)


def _render_hedge_bar(charm: float, vanna: float, delta: float):
    """Render stacked bar showing contribution of each source."""
    fig = go.Figure()

    # Only show non-zero values
    values = []
    labels = []
    colors = []

    if charm != 0:
        values.append(charm)
        labels.append('Charm')
        colors.append('#f97316')  # Orange

    if vanna != 0:
        values.append(vanna)
        labels.append('Vanna')
        colors.append('#8b5cf6')  # Purple

    if delta != 0:
        values.append(delta)
        labels.append('Delta Flow')
        colors.append('#3b82f6')  # Blue

    if not values:
        st.caption("No hedge activity")
        return

    for i, (val, label, color) in enumerate(zip(values, labels, colors)):
        fig.add_trace(go.Bar(
            name=label,
            x=['Hedge'],
            y=[val],
            marker_color=color,
            text=[f"{val:+,.0f}"],
            textposition='inside',
        ))

    fig.update_layout(
        barmode='relative',
        height=120,
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis_title="ES Contracts",
        xaxis_visible=False,
    )

    # Zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

    st.plotly_chart(fig, use_container_width=True)


def render_combined_hedge_compact(
    charm_es: float,
    vanna_es: float,
    delta_flow_es: float,
):
    """
    Render a compact single-line combined hedge metric.

    For use in summary rows where space is limited.
    """
    total = charm_es + vanna_es + delta_flow_es

    if total > 50:
        direction = "BUY"
        color = "🟢"
    elif total < -50:
        direction = "SELL"
        color = "🔴"
    else:
        direction = "NEUTRAL"
        color = "🟡"

    st.metric(
        "Combined Hedge",
        f"{color} {total:+,.0f} ES",
        delta=f"C:{charm_es:+.0f} V:{vanna_es:+.0f} D:{delta_flow_es:+.0f}",
    )
