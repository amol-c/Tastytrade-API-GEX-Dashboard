"""
Greek Dominance Timer Component
Shows which Greek (Vanna vs Charm) dominates based on time to expiry.
"""
import streamlit as st
from datetime import datetime


def render_greek_dominance_timer(expiry: str):
    """
    Show which Greek dominates based on time to expiry.

    Timeline:
    - >5 hours: Vanna dominant (IV events matter more)
    - 3-5 hours: Mixed (both active)
    - 1-3 hours: Charm dominant (time decay accelerating)
    - <1 hour: Charm explosion (gamma/charm at max)

    Args:
        expiry: Option expiry in YYMMDD format
    """
    if not expiry:
        return

    try:
        expiry_date = datetime.strptime(expiry, "%y%m%d")
        expiry_datetime = expiry_date.replace(hour=16, minute=0)
        now = datetime.now()
        time_remaining = expiry_datetime - now

        hours_remaining = time_remaining.total_seconds() / 3600

        if hours_remaining <= 0:
            st.caption("⏰ Options expired")
            return

        # Determine dominance based on time
        if hours_remaining > 5:
            dominant = "VANNA"
            vanna_pct = 70
            charm_pct = 30
            color = "🟣"
            desc = "IV events have more impact"
        elif hours_remaining > 3:
            dominant = "MIXED"
            vanna_pct = 50
            charm_pct = 50
            color = "🟡"
            desc = "Both Greeks active"
        elif hours_remaining > 1:
            dominant = "CHARM"
            vanna_pct = 30
            charm_pct = 70
            color = "🟠"
            desc = "Time decay accelerating"
        else:
            dominant = "CHARM"
            vanna_pct = 10
            charm_pct = 90
            color = "🔴"
            desc = "Charm/Gamma explosion"

        # Display
        col1, col2, col3 = st.columns([1, 2, 1])

        with col1:
            hrs = int(hours_remaining)
            mins = int((hours_remaining - hrs) * 60)
            st.metric("Time to Expiry", f"{hrs}h {mins}m")

        with col2:
            st.markdown(f"**{color} {dominant} Zone** - {desc}")
            st.progress(charm_pct / 100, text=f"Vanna {vanna_pct}% | Charm {charm_pct}%")

        with col3:
            st.metric("Dominant Greek", dominant)

    except Exception:
        pass
