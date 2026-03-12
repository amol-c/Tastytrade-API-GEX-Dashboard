"""
Account Settings Component
Handles credential management UI
"""
import streamlit as st
import os
import sys
import time


def _get_app_directory() -> str:
    """Get the application directory (works for frozen and dev)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def reset_credentials() -> bool:
    """
    Delete credentials and token files.
    Returns True if files were deleted.
    """
    app_dir = _get_app_directory()
    files_deleted = False

    # Files to delete
    files_to_delete = ['.env', 'tasty_token.json', 'streamer_token.json']

    for filename in files_to_delete:
        filepath = os.path.join(app_dir, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                files_deleted = True
            except Exception:
                pass

    return files_deleted


def render_account_settings():
    """Render the account settings section in sidebar."""
    with st.expander("🔑 Account"):
        st.caption("Manage your Tastytrade API credentials")

        if st.button("Reset Credentials", type="secondary", use_container_width=True,
                    help="Clear saved credentials and re-enter them"):
            reset_credentials()
            st.success("Credentials cleared! Restarting...")
            time.sleep(1)
            st.rerun()
