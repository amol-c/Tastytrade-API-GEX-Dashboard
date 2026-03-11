"""
VIX Display Component
Displays VIX chart and current level.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.vix_tracker import VIXHistoryTracker


def render_vix_section(current_vix: float, direction: str, change_pct: float, date_str: str):
    """
    Render the VIX section with chart.

    Args:
        current_vix: Current VIX level
        direction: "RISING", "FALLING", or "FLAT"
        change_pct: Percentage change
        date_str: Date in YYMMDD format for history
    """
    st.subheader("VIX")

    # Current metrics
    arrow = "↑" if direction == "RISING" else "↓" if direction == "FALLING" else "→"
    color = "red" if direction == "RISING" else "green" if direction == "FALLING" else "gray"

    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            "VIX Level",
            f"{current_vix:.2f}",
            delta=f"{arrow} {change_pct:+.1f}%",
            delta_color="inverse" if direction == "RISING" else "normal"
        )
    with col2:
        st.metric("IV Direction", direction)

    # Chart
    _render_vix_chart(date_str, current_vix, direction)


def _render_vix_chart(date_str: str, current_vix: float, direction: str, limit: int = 50):
    """Render VIX over time chart."""
    tracker = VIXHistoryTracker(date_str=date_str)
    history = tracker.get_history(limit=limit)

    if len(history) < 2:
        st.caption("VIX chart will appear after multiple data fetches")
        return

    hist_df = pd.DataFrame(history)
    hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'])

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
