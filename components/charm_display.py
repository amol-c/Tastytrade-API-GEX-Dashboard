"""
Charm Flow Display Component
Displays ES futures equivalent and historical charm data.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.charm_history import CharmHistoryTracker, calculate_es_futures_equivalent


def render_charm_section(analysis, expiry: str):
    """
    Render the charm flow section with ES futures equivalent.

    Args:
        analysis: MarketAnalysis object with charm_flow data
        expiry: Option expiry in YYMMDD format
    """
    st.divider()
    st.subheader("Charm Flow - ES Futures Equivalent")

    st.caption("ES contracts dealers will trade due to delta decay (+ = BUY, - = SELL)")

    with st.expander("ℹ️ What does Net Charm mean?"):
        st.markdown("""
**Charm = Delta decay over time**

- **Negative charm** → OTM options decaying → dealers unwind hedges → **BUY** pressure (bullish)
- **Positive charm** → ITM options solidifying → dealers add hedges → **SELL** pressure (bearish)

*Based on SpotGamma dealer positioning model: dealers are long calls, short puts.*
""")

    # Check if current charm data is available
    has_current_data = analysis and analysis.charm_flow.net_charm is not None

    if has_current_data:
        # Calculate current ES futures
        current_es = calculate_es_futures_equivalent(
            analysis.charm_flow.net_charm,
            analysis.current_price
        )
        # Display current metrics
        _render_current_metrics(analysis, current_es)
    else:
        current_es = None
        st.warning("⚠️ Current charm unavailable - insufficient options with valid IV and OI (showing historical data)")

    # Always display historical chart if data exists
    _render_history_chart(current_es, expiry)


def _render_current_metrics(analysis, current_es):
    """Render current charm metrics."""
    es_col1, es_col2, es_col3 = st.columns(3)

    with es_col1:
        es_sign = "-" if current_es < 0 else "+"
        st.metric(
            "ES Futures to Neutralize",
            f"{es_sign}{abs(current_es):,.0f} contracts",
        )
    with es_col2:
        st.metric("Flow Direction", analysis.charm_flow.direction)
    with es_col3:
        st.metric("Net Charm", f"${analysis.charm_flow.net_charm:,.0f}")


def _render_history_chart(current_es, expiry: str, limit=50):
    """Render ES contracts over time chart."""
    charm_tracker = CharmHistoryTracker(expiry=expiry)
    history = charm_tracker.get_es_futures_series(limit=limit)

    if len(history) < 2:
        st.caption("Chart will appear after multiple data fetches")
        return

    st.caption("ES Contracts Over Time")
    hist_df = pd.DataFrame(history)
    hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'], utc=True)

    # Determine color based on current or last known direction
    if current_es is not None:
        last_es = current_es
    else:
        last_es = hist_df['es_futures'].iloc[-1]

    line_color = 'red' if last_es < 0 else 'green'
    fill_color = 'rgba(255,0,0,0.1)' if last_es < 0 else 'rgba(0,255,0,0.1)'

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

    fig.update_layout(
        height=250,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_title="Time",
        yaxis_title="ES Contracts",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)
