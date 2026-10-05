#!/usr/bin/env python3
"""Reset a local user's password directly in the database.

This is the guaranteed "forgot password" method for localhost: it needs no
email setup and always works on the machine where the software is installed.

Usage (run from this folder, the software's root):
    python reset_password.py                      # interactive prompts
    python reset_password.py --user admin --new-password MyNewPass123

The database used is the same one the app uses (DATA_DIR / volume path).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

# SECRET_KEY is only needed for JWT/Fernet; password hashing doesn't use it,
# so a placeholder is fine for this local recovery tool.
os.environ.setdefault("SECRET_KEY", "localhost-password-reset-tool")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# NOTE: DATA_DIR must be decided BEFORE any backend.* import, because
# backend.config resolves the database path at import time.


def _default_data_dir() -> str:
    """Same location the desktop app itself uses (mirrors backend/launcher.py).

    Ensures the reset tool always opens the REAL database, never a stray copy.
    """
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


# Point at the app's real database before backend.config is imported.
os.environ.setdefault("DATA_DIR", _default_data_dir())

from backend.auth import get_user_by_email, hash_password  # noqa: E402
from backend.config import DB_PATH  # noqa: E402
from backend.db import engine as _engine  # noqa: E402
from backend.db import get_db, init_db  # noqa: E402
from sqlalchemy import inspect as _inspect  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset a B2B AI Lead Scraper user password.")
    ap.add_argument("--user", default=None, help="username/email (default: prompt)")
    ap.add_argument("--new-password", default=None, help="new password (default: prompt, hidden)")
    args = ap.parse_args()

    username = args.user or input("Username/email [admin]: ").strip() or "admin"

    if not os.path.exists(DB_PATH):
        print(f"ERROR: database not found at:\n  {DB_PATH}")
        print("If the app stores its data elsewhere, set DATA_DIR first, e.g.:")
        print('  set DATA_DIR=C:\\path\\to\\data && python reset_password.py')
        return 1

    if "users" not in _inspect(_engine).get_table_names():
        print(f"ERROR: no user accounts in database at:\n  {DB_PATH}")
        print("This does not look like the app's database. If the app stores")
        print("its data elsewhere, set DATA_DIR first, e.g.:")
        print('  set DATA_DIR=C:\\path\\to\\data && python reset_password.py')
        return 1

    db = next(get_db())
    try:
        init_db()  # ensure latest columns (e.g. pwd_reset_version) exist
        user = get_user_by_email(db, username)
        if not user:
            print(f"ERROR: no user found with username/email '{username}'.")
            print(f"(database: {DB_PATH})")
            return 1

        new_pw = args.new_password
        if not new_pw:
            new_pw = getpass.getpass("New password (min 4 characters): ")
            confirm = getpass.getpass("Confirm new password: ")
            if new_pw != confirm:
                print("ERROR: passwords do not match.")
                return 1
        if len(new_pw) < 4:
            print("ERROR: password must be at least 4 characters.")
            return 1

        user.password_hash = hash_password(new_pw)
        user.must_change_password = False
        user.pwd_reset_version = (user.pwd_reset_version or 0) + 1  # burn reset links
        db.commit()
        print(f"OK: password for '{user.email}' has been reset.")
        print("You can now sign in with the new password.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
