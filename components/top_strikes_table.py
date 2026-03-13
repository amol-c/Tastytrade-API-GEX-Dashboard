"""
Top Strikes Table Component

Displays tabbed tables showing top strikes by OI, Volume, and P/C Ratio.
Includes tick data (buy/sell flow) when available.

Single Responsibility: Render top strikes tables with optional tick data.
"""
import streamlit as st
import pandas as pd
from typing import Optional


def render_top_strikes_table(strike_df: pd.DataFrame):
    """
    Render the Top Strikes tables with tabs.

    Args:
        strike_df: DataFrame with strike data from aggregate_by_strike()
    """
    if strike_df.empty:
        st.info("No strike data available")
        return

    st.subheader("🔝 Top Strikes")

    # Create tabs for different views
    tab1, tab2, tab3 = st.tabs(["By Total OI", "By Total Volume", "By Put/Call Ratio"])

    with tab1:
        _render_oi_tab(strike_df)

    with tab2:
        _render_volume_tab(strike_df)

    with tab3:
        _render_pc_ratio_tab(strike_df)


def _render_oi_tab(strike_df: pd.DataFrame):
    """Render the Total OI tab with optional tick data."""
    # Check if we have tick data
    has_tick_data = 'buy_volume' in strike_df.columns and strike_df['buy_volume'].sum() > 0

    if has_tick_data:
        top_oi = strike_df.nlargest(10, 'total_oi')[
            ['strike', 'call_oi', 'put_oi', 'total_oi', 'buy_volume', 'sell_volume', 'net_flow']
        ].copy()
        top_oi['strike'] = top_oi['strike'].apply(lambda x: f"${x:,.0f}")
        top_oi['net_flow'] = top_oi['net_flow'].apply(lambda x: f"+{x:,}" if x > 0 else f"{x:,}")
        top_oi.columns = ['Strike', 'Call OI', 'Put OI', 'Total OI', 'Buy', 'Sell', 'Net Flow']

        # Show legend for tick data
        st.caption("Buy/Sell = TimeAndSale tick flow | Net Flow = Buy - Sell (OI change estimate)")
    else:
        top_oi = strike_df.nlargest(10, 'total_oi')[
            ['strike', 'call_oi', 'put_oi', 'total_oi']
        ].copy()
        top_oi['strike'] = top_oi['strike'].apply(lambda x: f"${x:,.0f}")
        top_oi.columns = ['Strike', 'Call OI', 'Put OI', 'Total OI']

    st.dataframe(top_oi, hide_index=True, use_container_width=True)


def _render_volume_tab(strike_df: pd.DataFrame):
    """Render the Total Volume tab."""
    top_vol = strike_df.nlargest(10, 'total_volume')[
        ['strike', 'call_volume', 'put_volume', 'total_volume']
    ].copy()
    top_vol['strike'] = top_vol['strike'].apply(lambda x: f"${x:,.0f}")
    top_vol.columns = ['Strike', 'Call Vol', 'Put Vol', 'Total Vol']
    st.dataframe(top_vol, hide_index=True, use_container_width=True)


def _render_pc_ratio_tab(strike_df: pd.DataFrame):
    """Render the Put/Call Ratio tab."""
    pc_ratio_df = strike_df.copy()
    pc_ratio_df['pc_ratio_oi'] = pc_ratio_df['put_oi'] / pc_ratio_df['call_oi'].replace(0, 1)
    pc_ratio_df['pc_ratio_vol'] = pc_ratio_df['put_volume'] / pc_ratio_df['call_volume'].replace(0, 1)

    top_pc = pc_ratio_df.nlargest(10, 'pc_ratio_oi')[
        ['strike', 'pc_ratio_oi', 'pc_ratio_vol', 'total_oi']
    ].copy()
    top_pc['strike'] = top_pc['strike'].apply(lambda x: f"${x:,.0f}")
    top_pc['pc_ratio_oi'] = top_pc['pc_ratio_oi'].apply(lambda x: f"{x:.2f}")
    top_pc['pc_ratio_vol'] = top_pc['pc_ratio_vol'].apply(lambda x: f"{x:.2f}")
    top_pc.columns = ['Strike', 'P/C Ratio (OI)', 'P/C Ratio (Vol)', 'Total OI']
    st.dataframe(top_pc, hide_index=True, use_container_width=True)
