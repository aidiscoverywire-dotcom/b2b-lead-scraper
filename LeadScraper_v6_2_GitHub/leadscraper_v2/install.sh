#!/usr/bin/env bash
#
# B2B AI Lead Scraper — one-command installer (Linux / macOS / WSL).
#
#   ./install.sh
#
# What it does:
#   1. Checks that Docker + Docker Compose are installed.
#   2. Creates a .env file with a random SECRET_KEY (if missing).
#   3. Builds and starts the app in the background.
#   4. Waits until the app answers, then prints the URL.
#
set -euo pipefail

cd "$(dirname "$0")"

say() { printf '\n==> %s\n' "$1"; }

# ---------- 1. Docker check ----------
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is not installed."
  echo "Install it from https://docs.docker.com/get-docker/ and run this script again."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "ERROR: Docker Compose was not found."
  echo "Install Docker Desktop (it includes Compose) from https://docs.docker.com/get-docker/"
  exit 1
fi

# ---------- 2. .env with a stable SECRET_KEY ----------
if [ ! -f .env ]; then
  say "Creating .env with a random SECRET_KEY..."
  if command -v openssl >/dev/null 2>&1; then
    KEY="$(openssl rand -hex 32)"
  else
    KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  sed "s/^SECRET_KEY=.*/SECRET_KEY=${KEY}/" .env.example > .env
  echo ".env created. Keep it safe — it encrypts your saved API keys."
else
  say ".env already exists, keeping it (SECRET_KEY unchanged)."
fi

# ---------- 3. Build + start ----------
say "Building and starting the app (first run downloads take a few minutes)..."
$COMPOSE up --build -d

# ---------- 4. Wait for health ----------
say "Waiting for the app to answer..."
PORT="$(grep -E '^PORT=' .env | cut -d= -f2)"
PORT="${PORT:-8000}"
for i in $(seq 1 40); do
  if curl -sf "http://localhost:${PORT}/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

if curl -sf "http://localhost:${PORT}/api/v1/health" >/dev/null 2>&1; then
  say "Done! Open the app here:"
  echo ""
  echo "    http://localhost:${PORT}"
  echo ""
  echo "Next steps:"
  echo "  1. Create your account (first screen)."
  echo "  2. The setup wizard will ask for your API keys"
  echo "     (Google Places, OpenAI, Apollo is optional)."
  echo "  3. Run your first lead search."
  echo ""
  echo "Useful commands:"
  echo "  $COMPOSE logs -f     # watch the logs"
  echo "  $COMPOSE down        # stop the app (your data is kept)"
else
  echo ""
  echo "The app did not answer in time. Check what happened with:"
  echo "  $COMPOSE logs"
  exit 1
fi
