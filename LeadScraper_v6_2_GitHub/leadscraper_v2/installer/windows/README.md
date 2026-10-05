# Windows installer project

This folder builds the **double-click installer** (`Setup_LeadScraper_v1.exe`)
that buyers install like normal software: double-click → Next → Next →
Finish. No Docker, no Python, no tech skills needed.

## How the buyer experience works

1. Buyer runs `Setup_LeadScraper_v1.exe`.
2. A desktop shortcut **"B2B AI Lead Scraper"** is created.
3. Buyer double-clicks the shortcut → the app starts and opens in its
   own desktop window automatically (no browser tab — uses the built-in
   Edge WebView2 engine on Windows 10/11; falls back to the browser only
   if the window backend is unavailable).
4. First-run setup: the launcher creates a private data folder
   (`%APPDATA%\LeadScraper\data`) and a secret key by itself — the buyer
   never touches it. They just create their account and enter API keys in
   the setup wizard, like before.

## Building the installer (on a Windows PC)

PyInstaller can only build a `.exe` on Windows, so this step runs on any
Windows 10/11 machine — yours, a friend's, or a cheap cloud VM.

**One-time requirements:** Python 3.12+ (tick "Add to PATH") and
Inno Setup 6 (free, https://jrsoftware.org/isdl.php).

**Build:**

```
double-click  build-windows.bat
```

That's it. Output: `installer\windows\Output\Setup_LeadScraper_v6.exe`

The script does everything: creates a venv, installs dependencies, runs
PyInstaller (`app.spec`), then compiles the installer (`setup.iss`).

## Files

| File                | Purpose                                              |
|---------------------|------------------------------------------------------|
| `build-windows.bat` | One-click build: exe + installer                     |
| `app.spec`          | PyInstaller recipe (bundles backend + web UI)        |
| `setup.iss`         | Inno Setup recipe (the actual installer wizard)      |
| `..\..\backend\launcher.py` | Desktop entry point: data folder, secret key, browser |

## Notes

- The installer is **per-user** (no admin rights needed).
- App data (users, keys, leads) lives in `%APPDATA%\LeadScraper\data` and
  survives updates.
- The console window stays visible while the app runs — it shows the URL
  and any errors. Closing it stops the app.
- macOS/Linux desktop builds: the same `app.spec` works there
  (`pyinstaller installer/windows/app.spec`); only the `.exe`/installer
  wrapper is Windows-specific.
