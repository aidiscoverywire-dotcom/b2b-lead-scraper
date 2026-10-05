# B2B AI Lead Scraper — Tier 1

AI-powered B2B lead generation: Google Places API (New) → optional Apollo
enrichment → email validation → AI pitch + lead score → CSV/Excel export.

Built from `LeadScraper_Tier1_Blueprint_v3_3.pdf` (the final build reference).

## Install

**Easiest:** `./install.sh` — one command, Docker-based
(see **[INSTALL.md](INSTALL.md)** for the full guide: one-command install,
Railway hosting, or manual Docker).

## What the buyer needs (BYOK)

Three API keys, entered once in the Setup Wizard (stored encrypted):

1. **Google Maps Platform key** — enable **Places API (New)** in Google Cloud
   Console. ~$10.86 per 500-lead run at current pricing (verify before launch);
   ~2 full runs/month inside the free tier.
2. **Apollo API key** — optional. Free keys include a limited monthly reveal
   pool (~75/mo per current reports); Basic ($49/mo) unlocks full-volume
   decision-maker emails. Without a key you still get full Places leads.
3. **OpenAI API key** — `gpt-4o-mini` writes a short pitch + lead score per lead.

No proxies, no Maps scraping, no LinkedIn scraping, no SMTP probing.

## Run locally

```bash
# Backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export DATA_DIR="$PWD/../data"
uvicorn backend.main:app --reload --port 8000   # from product/ root

# Frontend (new terminal)
cd frontend
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env
npm run dev   # http://localhost:5173
```

`SECRET_KEY` is required — the server refuses to boot without it, and API keys
are encrypted with a key derived from it. Keep it stable: changing it orphans
stored keys.

## Deploy on Railway (single container)

1. Push this `product/` folder to a GitHub repo, or `railway init` locally.
2. `railway up` — the Dockerfile builds frontend + backend into one service.
3. **Variables** → add `SECRET_KEY` (generate with the command above).
4. **Volumes** → create a volume mounted at `/app/data` (SQLite persistence).
5. Deploy. The app serves UI + API on `$PORT` automatically.

## Login

Default login: **admin** / **123**. The app makes sure this account always
exists — if it is ever missing (e.g. the database was created before this
fix), it is re-created automatically on startup. Changing the password is
optional (Settings → Security); nothing forces or nags you about it.

## Forgot your password?

Easiest first:

1. **ResetPassword.exe** (installed Windows app) — open the Start Menu →
   LeadScraper → **Reset Password**, type your username and new password. Done.
   No Python needed.
2. **reset_password.bat** (source folder, Windows) — double-click it and follow
   the prompts. Needs Python installed.
3. **reset_password.py** (any OS, terminal) — in the software folder run:

   ```bash
   python reset_password.py --user admin --new-password YourNewPassword
   ```

   (Run with no arguments for interactive prompts.)
4. **In-app reset link** — click **Forgot password?** on the sign-in screen.
   If you configured SMTP in Settings → Email, a 30-minute reset link is
   emailed to you. Without SMTP, the screen points you to the options above.

All methods work on localhost with no internet email setup required
(except option 4, which needs your own SMTP account).

## Tests

```bash
cd backend && . .venv/bin/activate
SECRET_KEY=test-only DATA_DIR=/tmp/ls_test pytest tests/ -q
```

## Compliance note

GDPR Notice Included (see in-app Settings). Not legal advice.

## Pricing disclaimer

Google/Apollo/OpenAI prices change — re-verify all vendor pricing immediately
before launch or listing. The in-app cost ticker uses $0.032/search page and
$0.02/detail call (Place Details Enterprise SKU).
