# Install Guide — B2B AI Lead Scraper

Pick the option that fits you. **Option A is the easiest.**

---

## Option A — One command (VPS / home server / WSL)

You need: a Linux/Mac machine (or VPS) with Docker installed.

```bash
unzip LeadScraper_Tier1_Product_v1.zip
cd product
./install.sh
```

That's it. The script:

1. Creates your secret config (`.env`) automatically
2. Builds and starts the app
3. Prints your app URL (usually `http://localhost:8000`)

Then open the URL, create your account, and the setup wizard will ask for
your API keys. Done.

**Useful commands** (run inside the `product/` folder):

| Command                      | What it does                    |
|------------------------------|---------------------------------|
| `docker compose logs -f`     | Watch the app logs              |
| `docker compose down`        | Stop the app (data is kept)     |
| `docker compose up -d`       | Start it again later            |

Your data (users, API keys, searches, leads) is stored in a Docker volume,
so it survives restarts and rebuilds.

---

## Option B — Railway (managed hosting, no server needed)

1. Upload this `product/` folder to a GitHub repository.
2. In [Railway](https://railway.app), create a **New Project → Deploy from
   GitHub repo**.
3. Railway auto-detects the `Dockerfile` and builds it.
4. Go to **Variables** and add:
   - `SECRET_KEY` — any long random string
     (generate: `openssl rand -hex 32`). Keep it forever — it encrypts
     your saved API keys.
5. Go to **Volumes** and add a volume mounted at `/app/data`
   (this keeps your database across deploys).
6. Open the public URL Railway gives you. Create your account, run the
   setup wizard, done.

---

## Option C — Manual Docker

```bash
cp .env.example .env
# edit .env and set a real SECRET_KEY
docker compose up --build -d
```

---

## What you need after installing

Three API keys (entered once in the app's setup wizard, stored encrypted):

1. **Google** — a Google Cloud key with **Places API (New)** enabled.
   This is the only required key for lead searching.
2. **OpenAI** — for AI pitch lines + lead scores (uses the cheap
   `gpt-4o-mini` model; a $5 credit lasts for months of testing).
3. **Apollo** — optional. Adds company/decision-maker enrichment.

You pay Google / OpenAI / Apollo directly — nothing goes through us.

## Requirements

- Docker 20.10+ with Docker Compose (Options A & C), or a Railway account
  (Option B).
- About 1 GB RAM free. Any modern VPS works.

## Troubleshooting

- **"Docker is not installed"** → install from
  https://docs.docker.com/get-docker/
- **App doesn't open** → run `docker compose logs` and check for errors.
  The most common cause is a missing `SECRET_KEY` in `.env`.
- **Port already in use** → change `PORT=` in `.env` to e.g. `8080`,
  then `docker compose up -d` again.
