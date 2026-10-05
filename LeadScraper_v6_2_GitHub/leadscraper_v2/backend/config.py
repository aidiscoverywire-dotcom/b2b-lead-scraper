"""Central configuration. All secrets come from the environment — nothing is
generated randomly at boot (see blueprint 7.4)."""
import os

# --- App version (shown in the UI topbar + /api/v1/meta) ----------------------
# Bump this on every release so a glance at the topbar proves which build is
# actually running (guards against stale frontend/dist being bundled).
APP_VERSION = "6.2.0"

# --- Required secrets -------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is required but not set. "
        "Set it to a long random string (e.g. `openssl rand -hex 32`) and keep "
        "it stable across restarts — Fernet-encrypted API keys in the DB "
        "depend on it."
    )

# --- Database path ----------------------------------------------------------
# Railway: RAILWAY_VOLUME_MOUNT_PATH is populated automatically when a volume
# is attached via the dashboard. Local dev: DATA_DIR, else /app/data with a
# fallback to ./data if /app/data is not writable.
def _resolve_db_path() -> str:
    mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if mount:
        return os.path.join(mount, "leadscraper.db")
    data_dir = os.environ.get("DATA_DIR", "/app/data")
    try:
        os.makedirs(data_dir, exist_ok=True)
        test = os.path.join(data_dir, ".writetest")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return os.path.join(data_dir, "leadscraper.db")
    except OSError:
        os.makedirs("./data", exist_ok=True)
        return os.path.join("./data", "leadscraper.db")

DB_PATH = _resolve_db_path()

# --- Upstream API base URLs -------------------------------------------------
PLACES_BASE = "https://places.googleapis.com/v1"
PLACES_SEARCH_URL = f"{PLACES_BASE}/places:searchText"
APOLLO_BASE = "https://api.apollo.io/v1"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"

# --- Auth -------------------------------------------------------------------
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# --- Cost accounting (verified against official Google pricing, Sep 2026) ----
# Text Search Pro: $32 / 1k  -> $0.032 per search page
# Place Details Enterprise: $20 / 1k -> $0.02 per detail call
# (our detail field mask triggers Enterprise; Google bills every request at
# the highest tier of any requested field)
COST_PER_SEARCH_PAGE = 0.032
COST_PER_DETAIL_CALL = 0.02

# --- Places fan-out ---------------------------------------------------------
SEARCH_PAGE_SIZE = 20
SEARCH_MAX_PAGES = 3          # 20 x 3 = 60 results cap per sub-query
DETAIL_CONCURRENCY = 10       # asyncio.Semaphore(10)

# --- Apollo -----------------------------------------------------------------
APOLLO_FREE_MONTHLY_POOL = 75  # per 2026 reports — verify at build
