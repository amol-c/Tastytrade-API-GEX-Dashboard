"""
App Paths - OS-specific data directory handling.

Development: Uses local ./data/ folder
Production (frozen app): Uses OS-specific app data folder:
- macOS: ~/Library/Application Support/GEX_Dashboard/
- Windows: %APPDATA%/GEX_Dashboard/
- Linux: ~/.local/share/GEX_Dashboard/
"""
import os
import sys

APP_NAME = "GEX_Dashboard"



def get_app_data_dir() -> str:
    """
    Get the app data directory.

    Development: ./data/
    Production: OS-specific app data folder

    Returns:
        Path to app data directory (created if doesn't exist)
    """
    # Development mode - use local data folder
    if not is_frozen():
        app_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(app_dir, exist_ok=True)
        return app_dir

    # Production (frozen app) - use OS-specific location
    if sys.platform == "darwin":
        # macOS
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        # Windows
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        # Linux and others
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))

    app_dir = os.path.join(base, APP_NAME)
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_data_folder(subfolder: str) -> str:
    """
    Get a data subfolder path within the app data directory.

    Args:
        subfolder: Name of subfolder (e.g., "charm_history", "tick_data")

    Returns:
        Full path to the subfolder (created if doesn't exist)

    Development: ./data/{subfolder}/
    Production: {app_data_dir}/data/{subfolder}/
    """
    base = get_app_data_dir()

    # In dev mode, get_app_data_dir() already returns ./data/
    # In production, we add a data/ subdirectory for organization
    if is_frozen():
        folder = os.path.join(base, "data", subfolder)
    else:
        folder = os.path.join(base, subfolder)

    os.makedirs(folder, exist_ok=True)
    return folder


def is_frozen() -> bool:
    """Check if running as frozen PyInstaller app."""
    return getattr(sys, 'frozen', False)
