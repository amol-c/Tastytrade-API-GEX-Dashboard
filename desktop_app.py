"""
Desktop Application Wrapper for GEX Dashboard

Uses pywebview to create a native desktop window that hosts the Streamlit app.
This file is the entry point for the packaged desktop application.

Usage:
    python desktop_app.py
"""
import sys
import os
import threading
import time
import socket


def get_app_path():
    """Get the application path (works for both dev and packaged)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def find_free_port(start=8501, max_attempts=10):
    """Find a free port starting from the given port."""
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('localhost', port))
                return port
            except OSError:
                continue
    return start  # Fallback


def run_streamlit_server_thread(port, app_path):
    """Run Streamlit server in a thread using bootstrap API."""
    # Change to app directory
    original_dir = os.getcwd()
    os.chdir(app_path)

    # Add app path to Python path
    if app_path not in sys.path:
        sys.path.insert(0, app_path)

    # Set environment variables before importing streamlit
    os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'
    os.environ['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'
    os.environ['STREAMLIT_SERVER_PORT'] = str(port)

    try:
        # Use bootstrap.run() for direct execution
        from streamlit.web import bootstrap
        dashboard_path = os.path.join(app_path, "app.py")

        # Run Streamlit using bootstrap (this is what 'streamlit run' does internally)
        # Signature: run(main_script_path, is_hello, args, flag_options)
        bootstrap.run(
            main_script_path=dashboard_path,
            is_hello=False,
            args=[],
            flag_options={
                "server.port": port,
                "server.headless": True,
                "browser.gatherUsageStats": False,
                "global.developmentMode": False,
            }
        )
    except Exception as e:
        print(f"Streamlit server error: {e}")
        import traceback
        traceback.print_exc()


def start_streamlit_thread(port):
    """Start Streamlit server in a background thread."""
    app_path = get_app_path()

    # Use threading for frozen apps (stays in same process, accesses all bundled modules)
    server_thread = threading.Thread(
        target=run_streamlit_server_thread,
        args=(port, app_path),
        daemon=True
    )
    server_thread.start()
    return server_thread


def start_streamlit_subprocess(port):
    """Start Streamlit server as subprocess (for development)."""
    import subprocess
    app_path = get_app_path()
    dashboard_path = os.path.join(app_path, "app.py")

    env = os.environ.copy()
    env['STREAMLIT_SERVER_HEADLESS'] = 'true'
    env['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'

    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            dashboard_path,
            f"--server.port={port}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--global.developmentMode=false"
        ],
        env=env,
        cwd=app_path
    )
    return process


def wait_for_server(port, timeout=30):
    """Wait for Streamlit server to be ready."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(('localhost', port))
                return True
        except (socket.error, socket.timeout):
            time.sleep(0.5)
    return False


def main():
    """Main entry point for desktop application."""
    try:
        import webview
    except ImportError:
        print("Error: pywebview is not installed.")
        print("Install it with: pip install pywebview")
        sys.exit(1)

    # Find available port
    port = find_free_port()
    print(f"Starting GEX Dashboard on port {port}...")

    # Start Streamlit server
    if getattr(sys, 'frozen', False):
        # Frozen app: use threading with bootstrap API
        print("Running in frozen mode, using internal Streamlit bootstrap...")
        server = start_streamlit_thread(port)
    else:
        # Development: use subprocess
        print("Running in development mode, using subprocess...")
        server = start_streamlit_subprocess(port)

    # Wait for server to be ready
    print("Waiting for server to start...")
    if not wait_for_server(port, timeout=60):
        print("Error: Server failed to start within timeout")
        if hasattr(server, 'terminate'):
            server.terminate()
        sys.exit(1)

    print("Server ready, opening window...")

    # Create native window
    webview.create_window(
        title="GEX Dashboard",
        url=f"http://localhost:{port}",
        width=1400,
        height=900,
        resizable=True,
        min_size=(800, 600)
    )

    # Start the GUI event loop (blocks until window is closed)
    webview.start()

    print("Window closed, shutting down...")

    # Clean up subprocess (thread will die with main process)
    if hasattr(server, 'terminate'):
        server.terminate()


if __name__ == "__main__":
    main()
