"""
Sentiment Display Component
Shows Dealer Gamma Ratio and Active Sentiment metrics.
"""
import streamlit as st
from typing import Dict, Optional
import pandas as pd

from utils.sentiment_calculator import SentimentCalculator


def render_sentiment_section(
    gex_metrics: Dict[str, float],
    strike_df: Optional[pd.DataFrame] = None,
):
    """
    Render the sentiment ratios section.

    Args:
        gex_metrics: Dict with call_gex, put_gex, net_gex, max_gex_strike
        strike_df: DataFrame with strike-level data for volume sentiment
    """
    st.subheader("📊 Sentiment Ratios")

    sentiment_calc = SentimentCalculator()
    col1, col2 = st.columns(2)

    with col1:
        dealer_result = sentiment_calc.calculate_from_gex_metrics(gex_metrics)
        st.metric(
            "Dealer Gamma Ratio",
            f"{dealer_result.ratio:.2f}",
            delta=dealer_result.label,
            delta_color="normal" if dealer_result.ratio >= 0.5 else "inverse",
            help="Call GEX / Total GEX. 1.0 = stabilizing, 0.0 = destabilizing, 0.5 = neutral."
        )
        st.progress(dealer_result.ratio)

    with col2:
        if strike_df is not None:
            sentiment_result = sentiment_calc.calculate_from_strike_df(strike_df)
            if sentiment_result:
                st.metric(
                    "Active Sentiment (Customers)",
                    f"{sentiment_result.ratio:.2f}",
                    delta=sentiment_result.label,
                    delta_color="normal" if sentiment_result.ratio >= 0.5 else "inverse",
                    help="Call Volume / Total Volume. 1.0 = bullish, 0.0 = bearish, 0.5 = neutral."
                )
                st.progress(sentiment_result.ratio)
            else:
                st.metric("Active Sentiment", "N/A", help="No volume data available")
        else:
            st.metric("Active Sentiment", "N/A", help="No volume data available")
