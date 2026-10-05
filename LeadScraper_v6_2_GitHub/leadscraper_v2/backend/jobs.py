"""Job orchestration + DB-backed SSE progress stream (blueprint 7.x).

The full pipeline: fan-out search -> details -> Apollo enrich -> email
validation -> AI pitch -> DB insert. All state lives in the jobs/leads
tables — no in-memory job store — so the SSE stream (and a restarted
server) reads progress straight from SQLite.
"""
import asyncio
import datetime
import json
import logging

from sqlalchemy.orm import Session

# NOTE: vendor SDK modules (places, apollo, ai, validate) are imported lazily
# inside run_job/_process_lead — they pull heavy third-party packages
# (openai, dnspython, phonenumbers, httpx) that are only needed while a job
# is actually running. Importing them at module top would slow every server
# start (and every desktop-app launch) for no benefit.
from .config import COST_PER_DETAIL_CALL, COST_PER_SEARCH_PAGE
from .crypto import decrypt_value
from .db import Job, Lead, SessionLocal

log = logging.getLogger(__name__)

VALID_KEY_NAMES = ("openai_key", "apollo_key", "google_maps_key")

# job_id -> asyncio.Task for in-flight runs
_running_tasks: dict[str, asyncio.Task] = {}


def get_user_keys(db: Session, user_id: int) -> dict[str, str]:
    """Decrypt the user's 3 API keys. Missing keys -> absent from dict."""
    from .db import Setting

    out: dict[str, str] = {}
    rows = db.query(Setting).filter(Setting.user_id == user_id).all()
    for row in rows:
        if row.key_name in VALID_KEY_NAMES:
            try:
                out[row.key_name] = decrypt_value(row.encrypted_value)
            except ValueError as exc:
                log.error("cannot decrypt %s: %s", row.key_name, exc)
    return out


def _log(db: Session, job: Job, message: str) -> None:
    stamp = datetime.datetime.utcnow().strftime("%H:%M:%S")
    job.error_log = (job.error_log or "") + f"[{stamp}] {message}\n"


def _passes_prefilters(detail: dict, filters: dict) -> bool:
    """Cheap filters that need only Places detail data.

    Applied BEFORE paid Apollo enrichment so credits are never spent
    on leads the user would reject anyway.
    """
    min_rating = filters.get("min_rating")
    if min_rating is not None and (detail.get("rating") or 0) < float(min_rating):
        return False
    min_reviews = filters.get("min_reviews")
    if min_reviews is not None and (detail.get("review_count") or 0) < int(min_reviews):
        return False
    return True


def _passes_postfilters(enrichment: dict, filters: dict) -> bool:
    """Filters that need enrichment data. Applied AFTER Apollo."""
    if filters.get("email_required") and not enrichment.get("decision_maker_email"):
        return False
    min_size = filters.get("min_company_size")
    if min_size:
        try:
            if int(enrichment.get("company_size") or 0) < int(min_size):
                return False
        except (TypeError, ValueError):
            pass
    return True


def _passes_filters(detail: dict, enrichment: dict, filters: dict) -> bool:
    return _passes_prefilters(detail, filters) and _passes_postfilters(enrichment, filters)


async def _process_lead(
    detail: dict,
    industry: str,
    filters: dict,
    apollo_key: str | None,
    openai_key: str | None,
    apollo_sem: asyncio.Semaphore,
    shared_http,
    ai_client,
) -> tuple[dict | None, int, str]:
    """Enrich + validate + pitch one lead. No DB access here.

    Returns (lead_fields | None, apollo_credits_used, error_note).
    None = filtered out or unusable.

    Vendor modules are imported here (cheap after the first call — Python
    caches imports) so server startup never pays for them.
    """
    from . import ai as ai_mod
    from . import apollo as apollo_mod
    from . import places as places_mod
    from . import validate as validate_mod

    phone = places_mod.normalize_phone(detail.get("phone_raw", ""), detail.get("region", ""))
    base = {
        "place_id": detail["place_id"],
        "name": detail.get("name", ""),
        "address": detail.get("address", ""),
        "phone": phone,
        "website": detail.get("website", ""),
        "rating": detail.get("rating"),
        "review_count": detail.get("review_count"),
        "types": ",".join(detail.get("types") or []),
        "industry": industry,
    }

    enrichment: dict = {}
    credits = 0
    note = ""
    if not _passes_prefilters(detail, filters):
        return None, 0, "filtered by rating/reviews"
    async with apollo_sem:
        try:
            status, enrichment, credits, note = await apollo_mod.enrich_lead(
                apollo_key, base, enrichment_enabled=bool(apollo_key), client=shared_http
            )
        except Exception as exc:  # never crash the run on enrichment
            log.warning("apollo enrich failed for %s: %s", detail["place_id"], exc)
            status, note = "basic", f"apollo error: {exc}"
    base["enrichment_status"] = status

    if not _passes_postfilters(enrichment, filters):
        return None, credits, note

    email = enrichment.get("decision_maker_email", "")
    # validate_email does blocking DNS lookups (up to 5s) — never run it on
    # the event loop or one slow MX lookup stalls all 25 workers.
    email_status = (
        await asyncio.to_thread(validate_mod.validate_email, email)
        if email
        else "unknown"
    )

    pitch, score = await ai_mod.generate_pitch_and_score(
        openai_key or "", base, client=ai_client
    )

    base.update(
        {
            "company_size": enrichment.get("company_size", ""),
            "company_industry": enrichment.get("industry", ""),
            "decision_maker_name": enrichment.get("decision_maker_name", ""),
            "decision_maker_title": enrichment.get("decision_maker_title", ""),
            "decision_maker_email": email,
            "email_status": email_status,
            "pitch": pitch,
            "lead_score": score,
        }
    )
    return base, credits, note


async def run_job(job_id: str) -> None:
    """Background pipeline for one job. Own DB session; never raises."""
    db: Session = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return
        keys = get_user_keys(db, job.user_id)
        google_key = keys.get("google_maps_key")
        if not google_key:
            job.status = "failed"
            _log(db, job, "No Google Maps API key saved. Add it in Settings first.")
            job.finished_at = datetime.datetime.utcnow()
            db.commit()
            return

        job.status = "running"
        db.commit()
        filters = job.filters or {}

        # Lazy vendor imports — see module docstring (startup speed).
        from . import ai as ai_mod
        from . import places as places_mod
        from .net import async_client as http_client

        # One shared HTTP client for the whole run (Places + Apollo), and one
        # OpenAI client — instead of a fresh connection pool per lead.
        shared_http = http_client()
        openai_key = keys.get("openai_key")
        ai_client = ai_mod.create_client(openai_key) if openai_key else None
        try:
            # --- 1. Fan-out search ---------------------------------------------
            async def on_page(n: int):
                job.sub_queries_run += n
                job.google_cost_usd += COST_PER_SEARCH_PAGE * n
                db.commit()

            try:
                found = await places_mod.search_places(
                    google_key, job.industry, job.location, job.max_leads,
                    on_page=on_page, client=shared_http,
                )
            except places_mod.PlacesError as exc:
                job.status = "failed"
                _log(db, job, f"Places search failed: {exc}")
                job.finished_at = datetime.datetime.utcnow()
                db.commit()
                return

            if not found:
                job.status = "completed"  # graceful: Found 0 of M requested
                _log(db, job, "Search returned no places for these sub-queries.")
                job.finished_at = datetime.datetime.utcnow()
                db.commit()
                return

            # --- 2. Details (Semaphore 10 inside) -------------------------------
            async def on_detail():
                job.detail_calls += 1
                job.google_cost_usd += COST_PER_DETAIL_CALL
                db.commit()

            try:
                details = await places_mod.get_place_details(
                    google_key, [f["place_id"] for f in found],
                    on_detail=on_detail, client=shared_http,
                )
            except places_mod.PlacesError as exc:
                job.status = "failed"
                _log(db, job, f"Places details failed: {exc}")
                job.finished_at = datetime.datetime.utcnow()
                db.commit()
                return

            # --- 3-5. Enrich + validate + pitch (bounded concurrency, no DB in workers)
            apollo_sem = asyncio.Semaphore(5)
            apollo_key = keys.get("apollo_key")

            async def worker(detail: dict):
                return await _process_lead(
                    detail, job.industry, filters, apollo_key, openai_key,
                    apollo_sem, shared_http, ai_client,
                )

            processed: list[tuple[dict | None, int, str]] = []
            for i in range(0, len(details), 25):
                batch = details[i : i + 25]
                processed.extend(await asyncio.gather(*(worker(d) for d in batch)))
        finally:
            await shared_http.aclose()
            if ai_client is not None:
                await ai_client.close()

        # --- 6. Insert leads (dedupe via place_id UNIQUE) ------------------------
        for fields, credits, note in processed:
            if credits:
                job.apollo_credits_used += credits
            if note:
                _log(db, job, note)
            if not fields:
                continue
            exists = (
                db.query(Lead)
                .filter(Lead.job_id == job.id, Lead.place_id == fields["place_id"])
                .first()
            )
            if exists:
                continue
            db.add(Lead(job_id=job.id, **{k: v for k, v in fields.items() if k != "industry"}))
            job.leads_found += 1
            db.commit()  # per-lead commit so SSE streams rows live

        job.status = "completed"
        job.finished_at = datetime.datetime.utcnow()
        db.commit()
        log.info("job %s completed: %d leads", job_id, job.leads_found)
    except Exception as exc:  # noqa: BLE001 — a job must never die silently
        log.exception("job %s crashed", job_id)
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = "failed"
                _log(db, job, f"Unexpected error: {exc}")
                job.finished_at = datetime.datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
        _running_tasks.pop(job_id, None)


def launch_job(job_id: str) -> None:
    task = asyncio.create_task(run_job(job_id))
    _running_tasks[job_id] = task


def recover_interrupted_jobs() -> int:
    """On boot: jobs stuck in 'running'/'pending' were interrupted by a restart.
    Mark them failed with a note (re-running would double-bill Google)."""
    db = SessionLocal()
    try:
        stuck = (
            db.query(Job)
            .filter(Job.status.in_(("running", "pending")))
            .all()
        )
        for job in stuck:
            job.status = "failed"
            _log(db, job, "Interrupted by server restart. Start a new search to retry.")
            job.finished_at = datetime.datetime.utcnow()
        db.commit()
        return len(stuck)
    finally:
        db.close()


def recover_interrupted_campaigns() -> int:
    """On boot: email campaigns stuck in 'pending'/'running' were interrupted
    by a restart (their background task is gone). Mark them failed with a
    note so the UI never shows a phantom 'sending…' forever."""
    from .db import EmailCampaign

    db = SessionLocal()
    try:
        stuck = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.status.in_(("pending", "running")))
            .all()
        )
        for camp in stuck:
            camp.status = "failed"
            camp.error_log = (camp.error_log or "") + "Interrupted by server restart.\n"
        db.commit()
        return len(stuck)
    finally:
        db.close()


# --- SSE -------------------------------------------------------------------------
def _lead_event(lead: Lead) -> str:
    payload = {
        "id": lead.id,
        "place_id": lead.place_id,
        "name": lead.name,
        "address": lead.address,
        "phone": lead.phone,
        "website": lead.website,
        "rating": lead.rating,
        "review_count": lead.review_count,
        "types": lead.types,
        "enrichment_status": lead.enrichment_status,
        "company_size": lead.company_size,
        "company_industry": lead.company_industry,
        "decision_maker_name": lead.decision_maker_name,
        "decision_maker_title": lead.decision_maker_title,
        "decision_maker_email": lead.decision_maker_email,
        "email_status": lead.email_status,
        "pitch": lead.pitch,
        "lead_score": lead.lead_score,
    }
    return f"event: lead\ndata: {json.dumps(payload)}\n\n"


def _progress_event(job: Job) -> str:
    payload = {
        "job_id": job.id,
        "status": job.status,
        "found": job.leads_found,
        "requested": job.max_leads,
        "message": f"Found {job.leads_found} of {job.max_leads} requested",
        "sub_queries_run": job.sub_queries_run,
        "detail_calls": job.detail_calls,
        "apollo_credits_used": job.apollo_credits_used,
        "google_cost_usd": round(job.google_cost_usd, 4),
    }
    return f"event: progress\ndata: {json.dumps(payload)}\n\n"


async def event_stream(job_id: str, user_id: int):
    """SSE generator reading state from the DB — resumable after restart."""
    last_lead_id = 0
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id, Job.user_id == user_id).first()
        if not job:
            yield "event: error\ndata: {\"message\": \"job not found\"}\n\n"
            return
        yield _progress_event(job)
        while True:
            db.expire_all()
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                yield "event: error\ndata: {\"message\": \"job deleted\"}\n\n"
                return
            new_leads = (
                db.query(Lead)
                .filter(Lead.job_id == job_id, Lead.id > last_lead_id)
                .order_by(Lead.id)
                .all()
            )
            for lead in new_leads:
                last_lead_id = lead.id
                yield _lead_event(lead)
            yield _progress_event(job)
            if job.status in ("completed", "failed"):
                terminal = "done" if job.status == "completed" else "error"
                payload = {
                    "job_id": job.id,
                    "status": job.status,
                    "found": job.leads_found,
                    "requested": job.max_leads,
                    "message": f"Found {job.leads_found} of {job.max_leads} requested",
                    "sub_queries_run": job.sub_queries_run,
                    "detail_calls": job.detail_calls,
                    "apollo_credits_used": job.apollo_credits_used,
                    "google_cost_usd": round(job.google_cost_usd, 4),
                    "error_log": job.error_log or "",
                }
                yield f"event: {terminal}\ndata: {json.dumps(payload)}\n\n"
                return
            await asyncio.sleep(1.0)
    finally:
        db.close()
