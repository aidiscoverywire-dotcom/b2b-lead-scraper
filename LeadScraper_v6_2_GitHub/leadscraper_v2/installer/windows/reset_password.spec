# PyInstaller spec — builds ResetPassword.exe (password recovery tool).
#
#   Windows:  pyinstaller installer\windows\reset_password.spec
#             -> dist\ResetPassword.exe   (ONEFILE: fully self-contained,
#                no _internal folder needed — safe to copy as a single file
#                next to the main app)
#   (build-windows.bat copies it into dist\LeadScraper\ so the installer
#   ships it next to the main app. No Python needed on the customer PC.)
#
# Console app: double-click -> enter username + new password -> done.

import os

PRODUCT_DIR = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
block_cipher = None

a = Analysis(
    [os.path.join(PRODUCT_DIR, "reset_password.py")],
    pathex=[PRODUCT_DIR],
    binaries=[],
    datas=[],
    hiddenimports=[
        "backend.auth",
        "backend.config",
        "backend.db",
        "sqlalchemy",
        "bcrypt",
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
# One-file build: everything is bundled INTO the exe (slower cold start,
# fine for a rarely-used recovery tool). No COLLECT section.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="ResetPassword",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
