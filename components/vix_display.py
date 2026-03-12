"""
VIX Display Component
Displays VIX chart and current level with slope-based trend.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from typing import Optional

from utils.vix_tracker import VIXHistoryTracker, VIXSlope


def render_vix_section(
    current_vix: float,
    direction: str,
    change_pct: float,
    date_str: str,
    vix_slope: Optional[VIXSlope] = None
):
    """
    Render the VIX section with chart and slope indicator.

    Args:
        current_vix: Current VIX level
        direction: "RISING", "FALLING", or "FLAT"
        change_pct: Percentage change per hour
        date_str: Date in YYMMDD format for history
        vix_slope: VIXSlope object with normalized slope
    """
    st.subheader("VIX")

    # Current metrics
    arrow = "↑" if direction == "RISING" else "↓" if direction == "FALLING" else "→"

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "VIX Level",
            f"{current_vix:.2f}",
            delta=f"{arrow} {change_pct:+.1f}%/hr",
            delta_color="inverse" if direction == "RISING" else "normal"
        )
    with col2:
        steepness = vix_slope.steepness if vix_slope else ""
        st.metric(
            "IV Trend",
            f"{direction}",
            delta=steepness if steepness and steepness != "FLAT" else None,
            delta_color="inverse" if direction == "RISING" else "normal" if direction == "FALLING" else "off"
        )
    with col3:
        if vix_slope:
            # Show normalized slope as a visual indicator
            slope_val = vix_slope.normalized_slope
            _render_slope_gauge(slope_val)
        else:
            st.metric("Slope", "N/A")

    # Chart
    _render_vix_chart(date_str, current_vix, direction)


def _render_slope_gauge(slope: float):
    """Render a visual gauge for normalized slope (-1 to +1)."""
    # Convert slope to percentage for progress bar (0 to 100)
    # -1 = 0%, 0 = 50%, +1 = 100%
    pct = int((slope + 1) * 50)
    pct = max(0, min(100, pct))

    # Color based on direction
    if slope > 0.1:
        color = "🔴"  # Rising IV = bearish
        label = f"+{slope:.2f}"
    elif slope < -0.1:
        color = "🟢"  # Falling IV = bullish
        label = f"{slope:.2f}"
    else:
        color = "⚪"
        label = f"{slope:.2f}"

    st.caption(f"Slope: {color} {label}")
    st.progress(pct / 100)
    st.caption("-1 ←— FLAT —→ +1")


def _render_vix_chart(date_str: str, current_vix: float, direction: str, limit: int = 50):
    """Render VIX over time chart."""
    tracker = VIXHistoryTracker(date_str=date_str)
    history = tracker.get_history(limit=limit)

    if len(history) < 2:
        st.caption("VIX chart will appear after multiple data fetches")
        return

    hist_df = pd.DataFrame(history)
    hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'], utc=True)

    # Color based on current direction
    line_color = 'red' if direction == "RISING" else 'green' if direction == "FALLING" else 'gray'
    fill_color = 'rgba(255,0,0,0.1)' if direction == "RISING" else 'rgba(0,255,0,0.1)' if direction == "FALLING" else 'rgba(128,128,128,0.1)'

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_df['timestamp'],
        y=hist_df['vix'],
        mode='lines+markers',
        name='VIX',
        line=dict(color=line_color, width=2),
        fill='tozeroy',
        fillcolor=fill_color
    ))

    fig.update_layout(
        height=200,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="",
        yaxis_title="VIX",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)
