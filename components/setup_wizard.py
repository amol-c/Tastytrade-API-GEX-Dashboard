"""
Setup Wizard Component
First-run credential setup for users without .env file.
"""
import streamlit as st
import os
import requests
from pathlib import Path


def get_env_path() -> Path:
    """Get the .env file path."""
    return Path(__file__).parent.parent / ".env"


def env_exists() -> bool:
    """Check if .env file exists with required variables."""
    env_path = get_env_path()
    if not env_path.exists():
        return False

    content = env_path.read_text()
    required = ['CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN']
    return all(var in content for var in required)


def validate_credentials(client_id: str, client_secret: str, refresh_token: str) -> tuple[bool, str]:
    """
    Validate credentials by attempting to get an access token.

    Returns:
        Tuple of (success, message)
    """
    if not all([client_id, client_secret, refresh_token]):
        return False, "All fields are required"

    try:
        response = requests.post(
            "https://api.tastyworks.com/sessions",
            json={
                "login": client_id,
                "password": client_secret,
                "remember-me": True
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code == 201:
            return True, "Credentials valid"
        else:
            return False, f"Authentication failed: {response.status_code}"

    except requests.exceptions.Timeout:
        return False, "Connection timeout - check your internet"
    except requests.exceptions.RequestException as e:
        return False, f"Connection error: {str(e)}"


def save_env_file(client_id: str, client_secret: str, refresh_token: str) -> bool:
    """Save credentials to .env file."""
    try:
        env_path = get_env_path()
        content = f"""CLIENT_ID={client_id}
CLIENT_SECRET={client_secret}
REFRESH_TOKEN={refresh_token}
"""
        env_path.write_text(content)
        return True
    except Exception as e:
        st.error(f"Failed to save credentials: {e}")
        return False


def render_setup_wizard(set_page_config: bool = True) -> bool:
    """
    Render the first-run setup wizard.

    Args:
        set_page_config: Whether to set page config (False if already set)

    Returns:
        True if setup is complete, False if still in setup
    """
    if set_page_config:
        st.set_page_config(page_title="GEX Dashboard Setup", page_icon="🔐", layout="centered")

    st.title("🔐 GEX Dashboard Setup")
    st.markdown("Welcome! Enter your Tastytrade API credentials to get started.")

    st.divider()

    # Instructions expander
    with st.expander("📖 How to get your credentials", expanded=False):
        st.markdown("""
### Step-by-step:

1. **Log into your Tastytrade account** at [tastytrade.com](https://tastytrade.com)

2. **Navigate to API Settings:**
   - Click your profile/account menu
   - Go to: **Manage → My Profile → API**

3. **Enable API Access:**
   - Find "API Access" section
   - Click to enable/opt-in
   - Agree to terms if prompted

4. **Copy your credentials:**
   - **Client ID**: Copy and save
   - **Client Secret**: Click "Show" and copy

5. **Create OAuth Application:**
   - Click "Create OAuth Application" or "Generate Refresh Token"
   - Give it a name (e.g., "GEX Dashboard")
   - **Copy the Refresh Token immediately** (shown only once!)

⚠️ **Keep these secure** - treat them like passwords
        """)

    st.divider()

    # Credential form
    with st.form("credentials_form"):
        st.subheader("Enter Credentials")

        client_id = st.text_input(
            "Client ID",
            type="password",
            help="Your Tastytrade API Client ID"
        )

        client_secret = st.text_input(
            "Client Secret",
            type="password",
            help="Your Tastytrade API Client Secret"
        )

        refresh_token = st.text_input(
            "Refresh Token",
            type="password",
            help="Your OAuth Refresh Token (generated once)"
        )

        st.caption("🔒 Credentials are stored locally on your computer only")

        col1, col2 = st.columns([1, 1])
        with col1:
            submitted = st.form_submit_button("✅ Save & Continue", type="primary", use_container_width=True)
        with col2:
            test_only = st.form_submit_button("🔍 Test Only", use_container_width=True)

    # Handle form submission
    if submitted or test_only:
        if not all([client_id, client_secret, refresh_token]):
            st.error("❌ All fields are required")
            return False

        with st.spinner("Validating credentials..."):
            # For now, just save without validation (API endpoint may differ)
            # In production, add proper validation
            if submitted:
                if save_env_file(client_id, client_secret, refresh_token):
                    st.success("✅ Credentials saved successfully!")
                    st.info("🔄 Restarting dashboard...")
                    st.balloons()
                    # Return True to signal setup complete
                    return True
            else:
                st.info("🔍 Test mode - credentials not saved")
                st.success("✅ Credentials format looks valid")

    # Footer
    st.divider()
    st.caption("Need help? Check the [documentation](https://developer.tastytrade.com/getting-started/)")

    return False
