"""
Dashboard Layout Component
Organizes the dashboard into logical tiers/sections.
"""
import streamlit as st


def render_tier1_summary():
    """
    TIER 1: SUMMARY
    Shows market bias, confidence, greek dominance timer.
    """
    st.header("🎯 Market Summary")


def render_tier2_exposure():
    """
    TIER 2: EXPOSURE CHARTS
    Shows GEX, VEx, Combined Flow by strike.
    """
    st.divider()
    st.header("📊 Dealer Exposure")


def render_tier3_flows():
    """
    TIER 3: GREEK FLOWS (Time Series)
    Shows VIX, Vanna ES, Charm ES over time.
    """
    st.divider()
    st.header("📈 Greek Flows")


def render_tier4_structure():
    """
    TIER 4: MARKET STRUCTURE
    Shows IV Skew, Volume/OI, Sentiment.
    """
    st.divider()
    st.header("📉 Market Structure")


def render_key_levels_expander(analysis):
    """Render key levels in an expander."""
    with st.expander("📍 Key Levels", expanded=False):
        level_col1, level_col2, level_col3, level_col4 = st.columns(4)

        with level_col1:
            gamma_flip = analysis.key_levels.gamma_flip
            st.metric("Gamma Flip", f"${gamma_flip:,.0f}" if gamma_flip else "N/A")

        with level_col2:
            if gamma_flip and analysis.current_price > gamma_flip:
                st.metric("Gamma Regime", "Positive", delta="Stabilizing")
            else:
                st.metric("Gamma Regime", "Negative", delta="Destabilizing", delta_color="inverse")

        with level_col3:
            cw = analysis.key_levels.call_wall
            st.metric("Call Wall", f"${cw:,.0f}" if cw else "N/A")

        with level_col4:
            pw = analysis.key_levels.put_wall
            st.metric("Put Wall", f"${pw:,.0f}" if pw else "N/A")

        st.caption("High Gamma Levels (within 10 strikes)")
        hg_col1, hg_col2, hg_col3, hg_col4 = st.columns(4)

        with hg_col1:
            hg_res1 = analysis.key_levels.hg_resistance_1
            st.metric("HG Resist 1", f"${hg_res1:,.0f}" if hg_res1 else "N/A")

        with hg_col2:
            hg_res2 = analysis.key_levels.hg_resistance_2
            st.metric("HG Resist 2", f"${hg_res2:,.0f}" if hg_res2 else "N/A")

        with hg_col3:
            hg_sup1 = analysis.key_levels.hg_support_1
            st.metric("HG Support 1", f"${hg_sup1:,.0f}" if hg_sup1 else "N/A")

        with hg_col4:
            hg_sup2 = analysis.key_levels.hg_support_2
            st.metric("HG Support 2", f"${hg_sup2:,.0f}" if hg_sup2 else "N/A")


def render_ai_prompt_expander(analysis):
    """Render AI analysis prompt in an expander."""
    with st.expander("🤖 AI Analysis Prompt"):
        st.code(analysis.to_ai_prompt(), language="markdown")
        st.caption("Copy this prompt and send to Claude or other AI for market assessment.")
