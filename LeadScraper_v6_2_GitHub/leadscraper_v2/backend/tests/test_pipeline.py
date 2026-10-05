"""Full pipeline test with mocked Google/Apollo/OpenAI transports (no real keys).

Exercises the REAL code paths in places.py / apollo.py / ai.py / jobs.py:
fan-out search + dedup, details, Apollo try-first + 402 degrade, filters,
cost accounting, SSE events, CSV/XLSX export, and graceful empty/403 cases.
"""
import asyncio
import json
import os
import sys
import tempfile
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-1234567890")
# Fresh database on every run — no state leaks between pytest invocations.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ls_pipeline_")

import httpx  # noqa: E402
import pytest  # noqa: E402

import backend.main as main  # noqa: E402
from backend import ai as ai_mod  # noqa: E402
from backend import apollo as apollo_mod  # noqa: E402
from backend import jobs as jobs_mod  # noqa: E402
from backend import places as places_mod  # noqa: E402
from backend import validate as validate_mod  # noqa: E402
from backend.crypto import encrypt_value  # noqa: E402
from backend.db import Job, Lead, SessionLocal, Setting, User  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PID_RATINGS = {"p1": 4.5, "p2": 4.8, "p3": 2.0, "p4": 4.2}  # p3 fails min_rating=4.0


def _detail_payload(pid: str) -> dict:
    website = "" if pid == "p4" else f"https://{pid}.example.com"
    return {
        "displayName": {"text": f"Business {pid}"},
        "formattedAddress": f"{pid} Main St, Austin, TX",
        "addressComponents": [{"types": ["country"], "shortText": "US"}],
        "internationalPhoneNumber": "+1 512-555-0100",
        "websiteUri": website,
        "rating": PID_RATINGS[pid],
        "userRatingCount": 120,
        "types": ["dentist"],
    }


class MockWorld:
    """Configurable fake upstream: places search/details, apollo, openai."""

    def __init__(self, people_match_status: int = 200, search_status: int = 200,
                 empty_search: bool = False):
        self.people_match_status = people_match_status
        self.search_status = search_status
        self.empty_search = empty_search
        self.search_calls = 0
        self.detail_calls = 0
        self.apollo_people_calls = 0
        self.seen_masks = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://places.googleapis.com/v1/places:searchText"):
            self.search_calls += 1
            self.seen_masks.add(request.headers.get("x-goog-fieldmask"))
            if self.search_status != 200:
                return httpx.Response(self.search_status, json={"error": "x"})
            if self.empty_search:
                return httpx.Response(200, json={"places": []})
            body = json.loads(request.content or b"{}")
            places = [
                {"id": "p1", "displayName": {"text": "Business p1"}},
                {"id": "p2", "displayName": {"text": "Business p2"}},
                {"id": "p3", "displayName": {"text": "Business p3"}},
            ]
            # duplicate p1/p2/p3 on page 2 of the first sub-query,
            # plus a fresh p4 -> exercises cross-page + cross-query dedup
            if self.search_calls == 1 and not body.get("pageToken"):
                return httpx.Response(200, json={"places": places, "nextPageToken": "t2"})
            if body.get("pageToken"):
                places.append({"id": "p4", "displayName": {"text": "Business p4"}})
            return httpx.Response(200, json={"places": places})
        if url.startswith("https://places.googleapis.com/v1/places/"):
            self.detail_calls += 1
            self.seen_masks.add(request.headers.get("x-goog-fieldmask"))
            pid = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json=_detail_payload(pid))
        if url.startswith("https://api.apollo.io/v1/organizations/enrich"):
            return httpx.Response(
                200,
                json={"organization": {"estimated_num_employees": 25,
                                      "industry": "Dentists"}},
            )
        if url.startswith("https://api.apollo.io/v1/people/match"):
            self.apollo_people_calls += 1
            if self.people_match_status != 200:
                return httpx.Response(self.people_match_status, json={})
            return httpx.Response(
                200,
                json={"person": {"name": "Jane Doe", "title": "Owner",
                                "email": "jane@p1.example.com"}},
            )
        return httpx.Response(404, json={})


class _FakeCompletions:
    async def create(self, **kwargs):
        assert kwargs.get("model") == "gpt-4o-mini"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"pitch": "Test pitch for outreach.", "score": 82}'))]
        )


class _FakeChat:
    completions = _FakeCompletions()


class _FakeOpenAI:
    def __init__(self, api_key=None, **kwargs):
        self.chat = _FakeChat()

    async def close(self):
        pass


@pytest.fixture()
def world(monkeypatch):
    w = MockWorld()
    real_client = httpx.AsyncClient

    def factory(*a, **k):
        return real_client(*a, transport=httpx.MockTransport(w.handler), **k)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    # ai.create_client() does `from openai import AsyncOpenAI` lazily at call
    # time, so patch the attribute on the real openai package.
    monkeypatch.setattr("openai.AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(validate_mod, "validate_email", lambda e: "valid")
    return w


def _make_user_with_keys(client: TestClient) -> tuple[int, str]:
    email = f"u_{uuid.uuid4().hex[:8]}@t.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "x" * 12})
    tok = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "x" * 12}
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        uid = user.id
        for name, val in (("openai_key", "sk-x"), ("apollo_key", "ap-x"),
                          ("google_maps_key", "g-x")):
            db.add(Setting(user_id=uid, key_name=name,
                           encrypted_value=encrypt_value(val)))
        db.commit()
    finally:
        db.close()
    return uid, h


def _run_job_direct(uid: int, **job_kwargs) -> Job:
    db = SessionLocal()
    job = Job(id=f"job_{uuid.uuid4().hex[:12]}", user_id=uid,
              industry="dentists", location="Austin, TX",
              max_leads=job_kwargs.get("max_leads", 10),
              filters=job_kwargs.get("filters", {}), status="pending")
    db.add(job)
    db.commit()
    jid = job.id
    db.close()
    asyncio.run(jobs_mod.run_job(jid))
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == jid).first()
    finally:
        db.close()


def test_full_pipeline_happy_path(world, tmp_path):
    with TestClient(main.app) as client:
        uid, h = _make_user_with_keys(client)
        job = _run_job_direct(uid, filters={"min_rating": 4.0})

        assert job.status == "completed", job.error_log
        # 4 unique places found; p3 filtered by min_rating -> 3 leads
        assert job.leads_found == 3
        # 10 sub-queries, first one paginated once -> 11 billed pages
        assert job.sub_queries_run == 11, job.sub_queries_run
        assert world.search_calls == 11
        # details fetched for all 4 unique places
        assert job.detail_calls == 4
        assert world.detail_calls == 4
        # cost: 11 x 0.032 + 4 x 0.02 = 0.432
        assert abs(job.google_cost_usd - 0.432) < 1e-9, job.google_cost_usd
        # explicit field masks sent on every Places call
        assert places_mod.SEARCH_FIELD_MASK in world.seen_masks
        assert places_mod.DETAIL_FIELD_MASK in world.seen_masks

        db = SessionLocal()
        try:
            leads = db.query(Lead).filter(Lead.job_id == job.id).all()
            assert len(leads) == 3
            by_pid = {ld.place_id: ld for ld in leads}
            assert set(by_pid) == {"p1", "p2", "p4"}  # dedup + filter verified
            for ld in leads:
                assert ld.pitch == "Test pitch for outreach."
                assert ld.lead_score == 82
                assert ld.phone == "+15125550100"  # E.164 normalized
            assert by_pid["p1"].email_status == "valid"
            assert by_pid["p2"].email_status == "valid"
            assert by_pid["p4"].email_status == "unknown"  # no email -> unknown
            assert by_pid["p1"].enrichment_status == "full"
            assert by_pid["p1"].decision_maker_email == "jane@p1.example.com"
            assert by_pid["p1"].company_size == "25"
            # p4 has no website -> no domain -> stays 'basic', no email invented
            assert by_pid["p4"].enrichment_status == "basic"
            assert by_pid["p4"].decision_maker_email == ""
        finally:
            db.close()

        # apollo credits: 1 per matched person (p1, p2); p4 no domain -> 0
        assert job.apollo_credits_used == 2, job.apollo_credits_used

        # exports contain the rows
        csv_resp = client.get(f"/api/v1/jobs/{job.id}/export?format=csv", headers=h)
        assert csv_resp.status_code == 200
        assert csv_resp.text.count("\n") == 4  # header + 3 rows
        assert "Business p1" in csv_resp.text
        xlsx_resp = client.get(f"/api/v1/jobs/{job.id}/export?format=xlsx", headers=h)
        assert xlsx_resp.status_code == 200
        assert len(xlsx_resp.content) > 1000

        # SSE: lead events + terminal done with honest Found N of M
        tok = h["Authorization"].split()[1]
        sse = client.get(f"/api/v1/jobs/{job.id}/stream?token={tok}")
        assert sse.status_code == 200
        assert sse.text.count("event: lead") == 3
        assert "event: done" in sse.text
        assert "Found 3 of 10 requested" in sse.text


def test_apollo_blocked_degrades_gracefully(world, monkeypatch):
    world.people_match_status = 402
    with TestClient(main.app) as client:
        uid, _ = _make_user_with_keys(client)
        job = _run_job_direct(uid)
        assert job.status == "completed", job.error_log
        assert job.leads_found == 4  # no rating filter here
        assert job.apollo_credits_used == 0
        db = SessionLocal()
        try:
            leads = db.query(Lead).filter(Lead.job_id == job.id).all()
            # org enrich still worked -> 'company'; people/match blocked -> no email
            assert {ld.enrichment_status for ld in leads} == {"company", "basic"}
            assert all(ld.decision_maker_email == "" for ld in leads)
        finally:
            db.close()
        assert "blocked" in (job.error_log or "").lower()


def test_empty_search_completes_gracefully(world):
    world.empty_search = True
    with TestClient(main.app) as client:
        uid, _ = _make_user_with_keys(client)
        job = _run_job_direct(uid)
        assert job.status == "completed"
        assert job.leads_found == 0
        assert job.detail_calls == 0


def test_places_403_fails_with_readable_message(world):
    world.search_status = 403
    with TestClient(main.app) as client:
        uid, _ = _make_user_with_keys(client)
        job = _run_job_direct(uid)
        assert job.status == "failed"
        assert "Places API (New)" in (job.error_log or "")


def test_same_place_in_two_jobs(world):
    """Per-job dedup: the same business may appear in two different jobs."""
    with TestClient(main.app) as client:
        uid, _ = _make_user_with_keys(client)
        job1 = _run_job_direct(uid, filters={"min_rating": 4.0})
        world.search_calls = 0  # mock paginates only the first search call; reset for job2
        job2 = _run_job_direct(uid, filters={"min_rating": 4.0})
        assert job1.id != job2.id
        assert job1.status == "completed" and job2.status == "completed"
        # happy path stores p1, p2, p4 (p3 filtered by rating) — in BOTH jobs
        assert job1.leads_found == 3, job1.leads_found
        assert job2.leads_found == 3, job2.leads_found
        db = SessionLocal()
        try:
            n1 = db.query(Lead).filter(Lead.job_id == job1.id).count()
            n2 = db.query(Lead).filter(Lead.job_id == job2.id).count()
        finally:
            db.close()
        assert (n1, n2) == (3, 3)
