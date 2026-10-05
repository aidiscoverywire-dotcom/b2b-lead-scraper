"""Desktop launcher — B2B AI Lead Scraper (v6).

Native window via pywebview (no Edge/Chrome required, no browser UI).
Fallback: plain browser tab when pywebview is unavailable.

Build flow (Windows):
    pip install pywebview pyinstaller
    pyinstaller installer/windows/app.spec

Window behaviour:
  • Proper title-bar with app name
  • Resizable, min 1100×700
  • No address bar, no browser tabs — looks like a real desktop app
  • Closing the window shuts the backend immediately — no stray processes
"""

import json
import logging
import os
import secrets
import stat
import sys
import threading
import time
import urllib.request

IS_FROZEN = getattr(sys, "frozen", False)
APP_TITLE  = "B2B AI Lead Scraper"
MIN_W, MIN_H = 1100, 700
START_W, START_H = 1280, 820


# ── helpers ──────────────────────────────────────────────────────────────────

def _data_dir() -> str:
    if os.environ.get("DATA_DIR"):
        return os.environ["DATA_DIR"]
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "LeadScraper", "data")
    elif sys.platform == "darwin":
        path = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support",
            "LeadScraper", "data",
        )
    else:
        path = os.path.join(os.path.expanduser("~"), ".leadscraper", "data")
    os.makedirs(path, exist_ok=True)
    return path


def _setup_logging(data_dir: str) -> str:
    log_file = os.path.join(data_dir, "launcher.log")
    # In PyInstaller windowed mode sys.stdout/stderr are None.
    # Redirect them early so uvicorn / click never get NoneType.isatty().
    if IS_FROZEN:
        _sink = open(log_file, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _sink
        if sys.stderr is None:
            sys.stderr = _sink
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if sys.stdout and not IS_FROZEN:
        logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    return log_file


def _fatal(msg: str) -> None:
    logging.error("FATAL: %s", msg)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, APP_TITLE, 0x10)
        except Exception:
            pass
    sys.exit(1)


def _ensure_secret_key(data_dir: str) -> str:
    if existing := os.environ.get("SECRET_KEY"):
        return existing
    key_file = os.path.join(data_dir, "secret.key")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            os.environ["SECRET_KEY"] = key
            return key
    key = secrets.token_hex(32)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key.encode())
    finally:
        os.close(fd)
    try:
        os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.environ["SECRET_KEY"] = key
    return key


def _frontend_dist() -> str:
    if v := os.environ.get("FRONTEND_DIST"):
        return v
    if IS_FROZEN:
        return os.path.join(sys._MEIPASS, "frontend", "dist")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "frontend", "dist")


def _wait_for_health(url: str, timeout: int = 60) -> bool:
    for _ in range(timeout):
        try:
            urllib.request.urlopen(url + "/api/v1/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def _already_running(url: str) -> bool:
    """True if OUR server is already answering on this URL (e.g. the user
    double-clicked the app icon). The 'app' marker distinguishes our server
    from any unrelated program on the same port."""
    try:
        with urllib.request.urlopen(url + "/api/v1/health", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return isinstance(data, dict) and data.get("app") == "leadscraper"
    except Exception:
        return False


def _find_free_port(start: int, attempts: int = 10) -> int | None:
    """If the preferred port is taken by something else, pick a free one.
    The frontend uses same-origin, so any port works transparently."""
    import socket

    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


# ── pywebview native window ───────────────────────────────────────────────────

def _open_native_window(url: str) -> bool:
    """
    Open a proper native desktop window using pywebview.
    Returns True if the window was opened and blocked until closed.
    Returns False if pywebview is not available (fallback to browser).
    """
    try:
        import webview  # pywebview
    except ImportError:
        logging.info("pywebview not installed — falling back to browser")
        return False

    # pywebview >= 5.0.1 blocks in-window file downloads unless explicitly
    # allowed (webview.settings['ALLOW_DOWNLOADS'] defaults to False).
    # Without this, JS-triggered downloads (blob-URL <a download> clicks)
    # are silently ignored inside the native window.
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # noqa: BLE001 — older pywebview: harmless no-op
        pass

    window = webview.create_window(
        title=APP_TITLE,
        url=url,
        width=START_W,
        height=START_H,
        min_size=(MIN_W, MIN_H),
        resizable=True,
        # Hide the URL bar entirely — this is a desktop app, not a browser
        text_select=True,
        background_color="#0f172a",   # matches dark splash while loading
    )

    # webview.start() blocks until all windows are closed; the caller shuts
    # the backend down right after it returns. If the native renderer fails
    # (e.g. WebView2 runtime missing), fall back to the browser instead of
    # crashing.
    try:
        webview.start(
            func=None,
            args=None,
            gui=None,          # auto-pick best GUI toolkit for the OS
            debug=not IS_FROZEN,
        )
    except Exception as exc:  # noqa: BLE001 — any renderer failure -> fallback
        logging.warning("pywebview window failed (%s) — falling back to browser", exc)
        return False
    return True


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    data_dir = _data_dir()
    # logging MUST come before any uvicorn / backend import
    log_file = _setup_logging(data_dir)
    _ensure_secret_key(data_dir)
    os.environ.setdefault("DATA_DIR", data_dir)
    os.environ.setdefault("FRONTEND_DIST", _frontend_dist())
    # Marks desktop runs (pywebview window, browser fallback, --no-browser).
    # Docker/Railway never set this — the frontend uses it to pick the working
    # export strategy (server-side save vs real browser download).
    os.environ.setdefault("DESKTOP_APP", "1")

    port = int(os.environ.get("PORT", "8000"))

    import uvicorn
    from backend.main import app  # env vars already set

    if "--no-browser" in sys.argv:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
        return

    url = f"http://127.0.0.1:{port}"
    logging.info("starting %s on %s", APP_TITLE, url)

    # Singleton: if our server is already running (user double-clicked the
    # icon), don't start a second server — just open a window onto it.
    # This instance owns no server, so closing its window kills nothing.
    server = None
    srv_thread = None
    if _already_running(url):
        logging.info("server already running — opening window on existing instance")
    else:
        free = _find_free_port(port)
        if free is None:
            _fatal(
                "Could not find a free port (tried %d–%d).\n\n"
                "Close the program using the port and try again." % (port, port + 9)
            )
        if free != port:
            port = free
            url = f"http://127.0.0.1:{port}"
            logging.info("port busy — using %s instead", url)
        # Start the FastAPI server in a background thread
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        srv_thread = threading.Thread(target=server.run, daemon=True)
        srv_thread.start()

        if not _wait_for_health(url):
            _fatal(
                "The app server did not start within 60 seconds.\n\n"
                "Please try reinstalling. If this keeps happening, send the log file to support:\n"
                + log_file
            )

    # Try pywebview native window first
    opened = _open_native_window(url)

    if not opened:
        # Fallback: open in the default browser
        import webbrowser
        logging.info("pywebview unavailable — opening in browser")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass

    # Graceful shutdown — only if this instance started the server
    if server is not None:
        logging.info("shutting down backend server")
        server.should_exit = True
        srv_thread.join(timeout=5)
    else:
        logging.info("window closed (server left running)")


if __name__ == "__main__":
    main()
