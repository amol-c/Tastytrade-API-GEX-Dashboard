# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for GEX Dashboard using streamlit-desktop-app
Works on Windows, macOS Intel, and macOS ARM
"""
import os
import sys
import tempfile
from PyInstaller.utils.hooks import collect_all, copy_metadata

# Project root - use current working directory (works in CI)
PROJECT_ROOT = os.path.abspath('.')

# Application data files
datas = [
    (os.path.join(PROJECT_ROOT, 'app.py'), '.'),
    (os.path.join(PROJECT_ROOT, 'simple_dashboard.py'), '.'),
    (os.path.join(PROJECT_ROOT, 'demo_dashboard.py'), '.'),
    (os.path.join(PROJECT_ROOT, 'components'), 'components'),
    (os.path.join(PROJECT_ROOT, 'utils'), 'utils'),
]

# Add .streamlit config if it exists
streamlit_config = os.path.join(PROJECT_ROOT, '.streamlit')
if os.path.exists(streamlit_config):
    datas.append((streamlit_config, '.streamlit'))

binaries = []
hiddenimports = [
    'streamlit',
    'streamlit_desktop_app',
    'components.setup_wizard',
    'components.sentiment_display',
    'components.vix_display',
    'components.combined_flow_display',
    'components.account_settings',
    'utils.auth',
    'utils.gex_calculator',
    'utils.vix_tracker',
    'simple_dashboard',
    'certifi',
    'ssl',
]

# Collect streamlit metadata and data
datas += copy_metadata('streamlit')
tmp_ret = collect_all('streamlit')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# Collect certifi for SSL certificates
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# Create the wrapper script content (same as streamlit-desktop-app does)
wrapper_script = '''
import sys
import os

# Add internal path for bundled modules
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    sys.path.insert(0, base_path)
    os.chdir(base_path)

from streamlit_desktop_app import start_desktop_app

if __name__ == "__main__":
    start_desktop_app(
        "app.py",
        title="GEX Dashboard",
        width=1400,
        height=900,
    )
'''

# Write wrapper script to temp location
wrapper_path = os.path.join(tempfile.gettempdir(), 'gex_wrapper.py')
with open(wrapper_path, 'w') as f:
    f.write(wrapper_script)

a = Analysis(
    [wrapper_path],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GEX_Dashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GEX_Dashboard',
)

# macOS app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='GEX Dashboard.app',
        icon=None,
        bundle_identifier='com.gexdashboard.app',
        info_plist={
            'CFBundleName': 'GEX Dashboard',
            'CFBundleDisplayName': 'GEX Dashboard',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
        },
    )
