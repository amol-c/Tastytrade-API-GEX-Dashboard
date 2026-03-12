"""
GEX Dashboard Application Entry Point

This is the main entry point that:
1. Checks if credentials are configured
2. Shows setup wizard if not
3. Runs the dashboard if configured

Usage:
    streamlit run app.py
"""
from components.setup_wizard import env_exists, render_setup_wizard

# Check credentials BEFORE any Streamlit imports/calls
# This ensures only one set_page_config is called
if not env_exists():
    # No credentials - show setup wizard
    import streamlit as st
    setup_complete = render_setup_wizard(set_page_config=True)
    if setup_complete:
        st.rerun()
else:
    # Credentials exist - run dashboard
    from simple_dashboard import main as dashboard_main
    dashboard_main()

