# B2B Lead Scraper — Frontend (Tier 1)

React + Vite + Tailwind CSS. 3 screens only: Setup Wizard, Lead Search, Settings.
(Plus a minimal sign-in gate — required because every backend endpoint needs JWT.)

## Run

```bash
cp .env.example .env   # set VITE_API_URL to your backend, e.g. http://localhost:8000
npm install
npm run dev            # http://localhost:5173
npm run build          # production bundle -> dist/
```

## Backend contract (Blueprint v3.3 §6)

All paths are relative to `<VITE_API_URL>/api`. Every path lives in
`src/api.js` (`ENDPOINTS`) — one place to change if the backend prefixes differ.

| Method & path | Body | Returns |
|---|---|---|
| POST /auth/register, /auth/login | {email, password} | {access_token} (or {token}) |
| GET /api/settings (JWT) | — | 3 keys, masked |
| POST /api/settings (JWT) | {key_name, value} | 200 — key_name: openai_key / apollo_key / google_maps_key |
| POST /api/wizard/test-openai | {key} | 200/400 (+ optional tier_hint/message) |
| POST /api/wizard/test-apollo | {key} | 200/400 + tier hint |
| POST /api/wizard/test-maps | {key} | 200/400 |
| POST /api/wizard/complete (JWT) | — | 200 |
| POST /api/search/start (JWT) | {industry, location, max_leads, filters:{min_rating,min_reviews,company_size,email_available}} | {job_id} |
| GET /api/search/stream/{job_id} | SSE, JWT passed as `?token=` query param (EventSource can't send headers) | events below |
| GET /api/search/jobs/{job_id} (JWT) | — | job row {status, ...} |
| GET /api/export/{job_id}?format=csv\|xlsx | — | file download |

### SSE event contract (JSON per message event)

```
{ "type": "lead",     "lead": { place_id, name, address, phone, website,
                                rating, reviews, enrichment: "full"|"company"|"basic",
                                email, email_status, pitch, score } }
{ "type": "progress", "leads": n, "requested": m, "searches": s, "details": d,
                      "google_cost_usd": x, "apollo_credits_used": c, "status": "running" }
{ "type": "done",     ...same counters }
{ "type": "error",    "message": "..." }
```

A message without `type` that looks like a lead row is treated as
`{type:"lead", lead:<message>}`.

## Notes

- Cost ticker math (v3.3, Enterprise SKU): Google = searches × $0.032 + details × $0.02.
- Wizard saves each key via POST /api/settings immediately after its test passes.
- Wizard completion is remembered in localStorage (`ls_wizard_done`).
- No proxy UI anywhere (removed per blueprint).
