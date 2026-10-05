# PyInstaller spec — builds the native desktop app (pywebview window).
#
#   Windows:  pyinstaller installer\windows\app.spec
#             -> dist\LeadScraper\LeadScraper.exe
#
# Requires (one-time):
#   pip install pywebview pyinstaller
#   pip install -r backend/requirements.txt
#
# pywebview on Windows uses the WebView2 Runtime (ships with Windows 11,
# auto-installed on Windows 10 via Microsoft update). If a user somehow
# lacks it, pywebview prompts them to install the Evergreen bootstrapper.

import os, sys

PRODUCT_DIR = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
block_cipher = None

a = Analysis(
    [os.path.join(PRODUCT_DIR, "backend", "launcher.py")],
    pathex=[PRODUCT_DIR],
    binaries=[],
    datas=[
        (os.path.join(PRODUCT_DIR, "frontend", "dist"),
         os.path.join("frontend", "dist")),
    ],
    hiddenimports=[
        # uvicorn
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan.on",
        # backend
        "backend.main", "backend.auth", "backend.config",
        "backend.crypto", "backend.db", "backend.export",
        "backend.jobs", "backend.wizard", "backend.net",
        # lazily-imported vendor modules (function-level imports — listed
        # explicitly so PyInstaller never misses them)
        "backend.places", "backend.apollo", "backend.ai", "backend.validate",
        # common
        "jose", "sqlalchemy", "pydantic", "httpx",
        "cryptography", "openpyxl", "dns", "dns.resolver",
        "email_validator", "phonenumbers", "openai",
        # pywebview — Windows uses EdgeChromium (WebView2)
        "webview",
        "webview.platforms.winforms",
        "clr_loader",
        "pythonnet",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LeadScraper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no console — native window only
    disable_windowed_traceback=False,
    icon=os.path.join(PRODUCT_DIR, "installer", "windows", "assets", "app.ico"),
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LeadScraper",
)
