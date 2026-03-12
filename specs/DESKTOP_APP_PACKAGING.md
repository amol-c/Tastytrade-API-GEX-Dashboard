# Desktop App Packaging Specification

## Overview

Package the GEX Dashboard as a standalone desktop application that non-technical users can download and run without installing Python or dependencies.

## Goals

1. **Single executable** - One file download (.exe for Windows, .app for Mac)
2. **No Python required** - All dependencies bundled
3. **First-run setup** - UI wizard for entering Tastytrade credentials
4. **Auto-builds** - GitHub Actions creates releases for Windows/Mac

---

## Technology Stack

| Component | Tool | Purpose |
|-----------|------|---------|
| Desktop wrapper | pywebview | Native window for Streamlit |
| Packaging | PyInstaller | Bundle Python + deps into executable |
| Build helper | streamlit-desktop-app | Simplifies packaging |
| CI/CD | GitHub Actions | Automated builds for Win/Mac |
| Credentials UI | Streamlit (built-in) | First-run setup wizard |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│           Desktop Application               │
├─────────────────────────────────────────────┤
│  ┌─────────────────────────────────────┐    │
│  │         PyWebView Window            │    │
│  │  ┌───────────────────────────────┐  │    │
│  │  │      Streamlit App            │  │    │
│  │  │  ┌─────────────────────────┐  │  │    │
│  │  │  │  Setup Wizard (if no    │  │  │    │
│  │  │  │  .env exists)           │  │  │    │
│  │  │  └─────────────────────────┘  │  │    │
│  │  │  ┌─────────────────────────┐  │  │    │
│  │  │  │  GEX Dashboard          │  │  │    │
│  │  │  └─────────────────────────┘  │  │    │
│  │  └───────────────────────────────┘  │    │
│  └─────────────────────────────────────┘    │
├─────────────────────────────────────────────┤
│  Bundled: Python 3.11 + all dependencies    │
└─────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Credential Setup UI

Create a setup wizard that appears when `.env` is missing.

**File:** `components/setup_wizard.py`

```python
def render_setup_wizard():
    """
    First-run setup wizard for entering Tastytrade credentials.
    Creates .env file after successful validation.
    """
    st.title("🔐 GEX Dashboard Setup")
    st.markdown("Enter your Tastytrade API credentials to get started.")

    with st.form("credentials_form"):
        client_id = st.text_input("Client ID", type="password")
        client_secret = st.text_input("Client Secret", type="password")
        refresh_token = st.text_input("Refresh Token", type="password")

        st.markdown("""
        **How to get credentials:**
        1. Log into [tastytrade.com](https://tastytrade.com)
        2. Go to: Manage → My Profile → API
        3. Enable API access and create OAuth application
        """)

        submitted = st.form_submit_button("Save & Continue")

        if submitted:
            if validate_credentials(client_id, client_secret, refresh_token):
                save_env_file(client_id, client_secret, refresh_token)
                st.success("✅ Credentials saved! Restarting...")
                st.rerun()
            else:
                st.error("❌ Invalid credentials. Please check and try again.")
```

**Integration in `simple_dashboard.py`:**

```python
from components.setup_wizard import render_setup_wizard, env_exists

def main():
    if not env_exists():
        render_setup_wizard()
        return

    # Normal dashboard code...
```

---

### Phase 2: Desktop App Wrapper

**File:** `desktop_app.py`

```python
"""
Desktop application wrapper for GEX Dashboard.
Uses pywebview to create native window.
"""
import webview
import subprocess
import threading
import time
import sys
import os

def get_app_path():
    """Get the application path (works for both dev and packaged)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def start_streamlit():
    """Start Streamlit server in background."""
    app_path = get_app_path()
    dashboard_path = os.path.join(app_path, "simple_dashboard.py")

    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        dashboard_path,
        "--server.headless=true",
        "--server.port=8501",
        "--browser.gatherUsageStats=false"
    ])

def main():
    # Start Streamlit in background thread
    server_thread = threading.Thread(target=start_streamlit, daemon=True)
    server_thread.start()

    # Wait for server to start
    time.sleep(3)

    # Create native window
    webview.create_window(
        "GEX Dashboard",
        "http://localhost:8501",
        width=1400,
        height=900,
        resizable=True
    )
    webview.start()

if __name__ == "__main__":
    main()
```

---

### Phase 3: PyInstaller Configuration

**File:** `gex_dashboard.spec`

```python
# -*- mode: python ; coding: utf-8 -*-
import os
import site
from PyInstaller.utils.hooks import collect_all, collect_data_files

# Get streamlit package location
streamlit_path = None
for path in site.getsitepackages():
    potential_path = os.path.join(path, 'streamlit')
    if os.path.exists(potential_path):
        streamlit_path = potential_path
        break

# Collect all necessary data
datas = [
    ('simple_dashboard.py', '.'),
    ('components', 'components'),
    ('utils', 'utils'),
    ('.streamlit', '.streamlit'),
]

# Add streamlit static files
if streamlit_path:
    datas.append((os.path.join(streamlit_path, 'static'), 'streamlit/static'))
    datas.append((os.path.join(streamlit_path, 'runtime'), 'streamlit/runtime'))

# Collect package data
packages_to_collect = ['streamlit', 'plotly', 'pandas', 'altair']
for pkg in packages_to_collect:
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
        datas.extend(pkg_datas)
    except:
        pass

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'streamlit',
        'streamlit.runtime.scriptrunner',
        'streamlit.web.cli',
        'plotly',
        'pandas',
        'websocket',
        'scipy',
        'scipy.stats',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GEX_Dashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',  # App icon
)

# For macOS, create .app bundle
app = BUNDLE(
    exe,
    name='GEX Dashboard.app',
    icon='assets/icon.icns',
    bundle_identifier='com.gexdashboard.app',
)
```

---

### Phase 4: GitHub Actions Workflow

**File:** `.github/workflows/build-desktop.yml`

```yaml
name: Build Desktop App

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:
    inputs:
      version:
        description: 'Version number'
        required: true
        default: '1.0.0'

jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyinstaller pywebview

      - name: Build executable
        run: |
          pyinstaller gex_dashboard.spec

      - name: Upload Windows artifact
        uses: actions/upload-artifact@v4
        with:
          name: GEX_Dashboard_Windows
          path: dist/GEX_Dashboard.exe

  build-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyinstaller pywebview

      - name: Build executable
        run: |
          pyinstaller gex_dashboard.spec

      - name: Create DMG
        run: |
          hdiutil create -volname "GEX Dashboard" -srcfolder "dist/GEX Dashboard.app" -ov -format UDZO "dist/GEX_Dashboard.dmg"

      - name: Upload macOS artifact
        uses: actions/upload-artifact@v4
        with:
          name: GEX_Dashboard_macOS
          path: dist/GEX_Dashboard.dmg

  create-release:
    needs: [build-windows, build-macos]
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/')
    steps:
      - name: Download all artifacts
        uses: actions/download-artifact@v4

      - name: Create Release
        uses: softprops/action-gh-release@v1
        with:
          files: |
            GEX_Dashboard_Windows/GEX_Dashboard.exe
            GEX_Dashboard_macOS/GEX_Dashboard.dmg
          draft: false
          prerelease: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## File Structure After Implementation

```
Tastytrade-API-GEX-Dashboard/
├── .github/
│   └── workflows/
│       └── build-desktop.yml      # GitHub Actions workflow
├── assets/
│   ├── icon.ico                   # Windows icon
│   └── icon.icns                  # macOS icon
├── components/
│   ├── setup_wizard.py            # NEW: Credential setup UI
│   └── ...existing components
├── specs/
│   └── DESKTOP_APP_PACKAGING.md   # This spec
├── desktop_app.py                 # NEW: Desktop wrapper
├── gex_dashboard.spec             # NEW: PyInstaller config
├── simple_dashboard.py            # Modified: Check for .env
└── requirements.txt               # Add: pywebview
```

---

## User Experience Flow

### First Run (No Credentials)

```
1. User downloads GEX_Dashboard.exe
2. Double-clicks to run
3. Setup wizard appears:
   ┌─────────────────────────────────────┐
   │  🔐 GEX Dashboard Setup             │
   │                                     │
   │  Enter your Tastytrade credentials: │
   │                                     │
   │  Client ID:     [______________]    │
   │  Client Secret: [______________]    │
   │  Refresh Token: [______________]    │
   │                                     │
   │  [Save & Continue]                  │
   └─────────────────────────────────────┘
4. Credentials validated via API
5. .env file created in app directory
6. Dashboard loads
```

### Subsequent Runs

```
1. User double-clicks GEX_Dashboard.exe
2. .env exists → Dashboard loads directly
3. Ready to use
```

---

## Requirements Updates

**Add to `requirements.txt`:**

```
pywebview>=4.0
```

**Development dependencies (not bundled):**

```
pyinstaller>=6.0
```

---

## Testing Plan

| Test Case | Expected Result |
|-----------|-----------------|
| Run without .env | Setup wizard appears |
| Enter invalid credentials | Error message, retry |
| Enter valid credentials | .env created, dashboard loads |
| Run with .env | Dashboard loads directly |
| Close window | App exits cleanly |
| Windows build | .exe runs on clean Windows |
| macOS build | .app runs on clean macOS |

---

## Security Considerations

1. **Credentials stored locally** - .env file in user's app directory
2. **No cloud transmission** - Credentials only sent to Tastytrade API
3. **Token caching** - Access tokens cached locally with expiry
4. **Input validation** - Credentials validated before saving

---

## Future Enhancements

1. **Auto-update** - Check for new versions on startup
2. **Settings UI** - Edit credentials without deleting .env
3. **Multiple accounts** - Support switching between accounts
4. **Portable mode** - Store settings alongside .exe

---

## Implementation Order

1. [ ] Create `components/setup_wizard.py`
2. [ ] Modify `simple_dashboard.py` to check for .env
3. [ ] Create `desktop_app.py` wrapper
4. [ ] Create `gex_dashboard.spec`
5. [ ] Add app icons to `assets/`
6. [ ] Create GitHub Actions workflow
7. [ ] Test local builds (Windows/Mac)
8. [ ] Test GitHub Actions builds
9. [ ] Create first release

---

## Commands Reference

**Local development:**
```bash
streamlit run simple_dashboard.py
```

**Test desktop wrapper:**
```bash
python desktop_app.py
```

**Build executable locally:**
```bash
pip install pyinstaller pywebview
pyinstaller gex_dashboard.spec
```

**Create release (via Git tag):**
```bash
git tag v1.0.0
git push origin v1.0.0
# GitHub Actions will build and create release
```
