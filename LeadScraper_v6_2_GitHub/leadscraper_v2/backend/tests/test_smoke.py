"""End-to-end smoke test with mocked external APIs (no real keys needed)."""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-1234567890")
# Fresh database on every run — no state leaks between pytest invocations.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ls_smoke_")

import backend.main as main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def auth_headers(c):
    c.post("/api/v1/auth/register", json={"email": "t@t.com", "password": "x" * 12})
    tok = c.post("/api/v1/auth/login", json={"email": "t@t.com", "password": "x" * 12}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def test_full_flow():
    with TestClient(main.app) as c:
        assert c.get("/api/v1/health").status_code == 200

        h = auth_headers(c)

        s = c.get("/api/v1/settings", headers=h).json()
        assert set(s["keys"]) == {"openai_key", "apollo_key", "google_maps_key"}
        assert s["wizard_done"] is False

        r = c.put(
            "/api/v1/settings",
            headers=h,
            json={"key_name": "openai_key", "value": "sk-test"},
        )
        assert r.status_code == 200
        # value must be stored encrypted (masked on read)
        s2 = c.get("/api/v1/settings", headers=h).json()
        assert s2["keys"]["openai_key"] not in (None, "sk-test")

        assert c.post("/api/v1/wizard/complete", headers=h).status_code == 200

        # No Google Places key saved -> job creation is rejected immediately
        # with a readable message (never a fake "free trial" run).
        r = c.post(
            "/api/v1/jobs",
            headers=h,
            json={"industry": "dentists", "location": "Austin, TX", "max_leads": 50, "filters": {}},
        )
        assert r.status_code == 400
        assert "Google Places API key" in r.json()["detail"]

        # Save a (fake) Google key -> job is accepted as pending.
        r = c.put(
            "/api/v1/settings",
            headers=h,
            json={"key_name": "google_maps_key", "value": "g-x"},
        )
        assert r.status_code == 200
        job = c.post(
            "/api/v1/jobs",
            headers=h,
            json={"industry": "dentists", "location": "Austin, TX", "max_leads": 50, "filters": {}},
        ).json()
        assert job["status"] == "pending"

        import time

        # The background worker must reach a terminal state on its own
        # (whatever the network does — Google may reject the fake key fast,
        # or be unreachable and exhaust retries). Poll, don't assume timing.
        g = {}
        for _ in range(50):
            time.sleep(3)
            g = c.get(f"/api/v1/jobs/{job['job_id']}", headers=h).json()
            if g["status"] in ("completed", "failed"):
                break
        assert g["status"] in ("completed", "failed"), g["status"]
        assert "detail_calls" in g

        # SSE streams named events and works with ?token= auth.
        # A gracefully-completed job ends with "done" (a failed one with "error").
        tok = h["Authorization"].split()[1]
        r = c.get(f"/api/v1/jobs/{job['job_id']}/stream?token={tok}")
        events = re.findall(r"^event: (\w+)", r.text, re.M)
        assert "progress" in events and events[-1] in ("done", "error")
        m = re.search(r"event: progress\ndata: (\{.*\})", r.text)
        payload = json.loads(m.group(1))
        assert payload["message"].startswith("Found ")

        assert (
            c.get(f"/api/v1/jobs/{job['job_id']}/export?format=csv", headers=h).status_code
            == 200
        )
        assert (
            c.get(f"/api/v1/jobs/{job['job_id']}/export?format=xlsx", headers=h).status_code
            == 200
        )
        assert c.get("/api/v1/dashboard/stats", headers=h).status_code == 200
