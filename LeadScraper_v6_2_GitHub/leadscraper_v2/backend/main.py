"""FastAPI app — B2B AI Lead Scraper (Tier 1) backend.

Run from the product/ directory:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import datetime
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import email_sender
from .auth import (
    authenticate,
    create_access_token,
    get_current_user,
    get_user_by_email,
    hash_password,
    verify_password,
)
from .config import APP_VERSION, JWT_ALGORITHM, SECRET_KEY

FRONTEND_DIST = os.environ.get("FRONTEND_DIST", "")
from .crypto import decrypt_value, encrypt_value
from .db import EmailCampaign, Job, Lead, Setting, User, get_db, init_db
from .export import export_csv, export_xlsx
from .jobs import (
    VALID_KEY_NAMES,
    event_stream,
    get_user_keys,
    launch_job,
    recover_interrupted_campaigns,
    recover_interrupted_jobs,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Default single-user login (blueprint: no public sign-up) ----------------------
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "123"
SMTP_SETTING_KEY = "smtp_config"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup/shutdown logic (official FastAPI lifespan pattern —
    @app.on_event("startup") is deprecated). Runs DB init, ensures the
    default admin exists, and recovers jobs/campaigns interrupted by a
    previous shutdown."""
    init_db()
    _ensure_default_admin()  # defined below; resolved when lifespan runs
    n = recover_interrupted_jobs()
    if n:
        log.info("marked %d interrupted job(s) as failed", n)
    m = recover_interrupted_campaigns()
    if m:
        log.info("marked %d interrupted email campaign(s) as failed", m)
    yield


app = FastAPI(title="B2B AI Lead Scraper — Tier 1", version="1.6.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_default_admin() -> None:
    """Make sure the out-of-the-box login (admin / 123) always works.

    The old logic only seeded on a completely empty users table, so if the
    user had ever registered their own account first, the default admin was
    never created and 'admin / 123' failed with 'Invalid username or
    password'. Now we ensure the admin account exists whenever it is
    missing. An existing admin account is NEVER touched (its password is
    not reset) — use reset_password.py if it was changed and forgotten.
    Changing the password is optional; nothing forces or nags the user.
    """
    db = next(get_db())
    try:
        if get_user_by_email(db, DEFAULT_ADMIN_USERNAME):
            return
        user = User(
            email=DEFAULT_ADMIN_USERNAME,
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            must_change_password=False,
        )
        db.add(user)
        db.commit()
        log.info("created default admin account (username=%s)", DEFAULT_ADMIN_USERNAME)
    finally:
        db.close()


# --- Schemas -------------------------------------------------------------------
class RegisterBody(BaseModel):
    email: str
    password: str = Field(min_length=8)


class LoginBody(BaseModel):
    email: str
    password: str


class KeyTestBody(BaseModel):
    key: str = ""


class JobCreateBody(BaseModel):
    industry: str
    location: str
    max_leads: int = Field(default=500, ge=1, le=1000)
    filters: dict = Field(default_factory=dict)


class SettingsPutBody(BaseModel):
    key_name: str
    value: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4)


class SmtpConfigBody(BaseModel):
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str
    from_name: str = ""
    use_tls: bool = True


class SmtpTestBody(BaseModel):
    to_email: str


class BulkEmailBody(BaseModel):
    subject: str
    body_html: str
    only_valid_email: bool = True


def _token_response(user: User) -> dict:
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


# --- Auth ------------------------------------------------------------------------
@app.post("/api/v1/auth/register", status_code=201)
def register(body: RegisterBody, db: Session = Depends(get_db)):
    if get_user_by_email(db, body.email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered.")
    user = User(email=body.email.lower().strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@app.post("/api/v1/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")
    return _token_response(user)


@app.put("/api/v1/auth/change-password")
def change_password(
    body: ChangePasswordBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    if len(body.new_password) < 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be at least 4 characters.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.pwd_reset_version = (user.pwd_reset_version or 0) + 1  # invalidate reset links
    db.commit()
    return {"ok": True}


# --- Forgot password (localhost-friendly) ---------------------------------------
RESET_TOKEN_EXPIRE_MINUTES = 30


class ForgotPasswordBody(BaseModel):
    email: str


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str = Field(min_length=4, max_length=128)


def _create_reset_token(user: User) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(
        minutes=RESET_TOKEN_EXPIRE_MINUTES
    )
    return jwt.encode(
        {
            "sub": str(user.id),
            "purpose": "pw-reset",
            "ver": user.pwd_reset_version or 0,
            "exp": expire,
        },
        SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def _verify_reset_token(token: str, db: Session) -> User | None:
    """Returns the user iff the token is valid AND unused (one-time).

    The token embeds the pwd_reset_version it was issued for; any password
    change bumps the version and invalidates all outstanding links.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("purpose") != "pw-reset":
        return None
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        return None
    if int(payload.get("ver", -1)) != (user.pwd_reset_version or 0):
        return None  # already used or superseded
    return user


@app.post("/api/v1/auth/forgot-password")
async def forgot_password(
    body: ForgotPasswordBody, request: Request, db: Session = Depends(get_db)
):
    """Request a password-reset link.

    Always returns ok:true (never reveals whether the email exists). If the
    user has SMTP configured in Settings, a 30-minute reset link is emailed.
    Otherwise email_sent=false and the UI points at reset_password.py, which
    always works on localhost without any email setup.
    """
    user = get_user_by_email(db, body.email or "")
    email_sent = False
    if user and user.is_active:
        cfg = _get_smtp_config(db, user.id)
        if cfg:
            token = _create_reset_token(user)
            # Same-origin by default (desktop app may run on any port);
            # APP_PUBLIC_URL overrides for proxied deploys.
            base = os.environ.get("APP_PUBLIC_URL") or str(request.base_url).rstrip("/")
            link = f"{base}/?reset_token={token}"
            html = (
                "<p>You requested a password reset for <strong>B2B AI Lead Scraper</strong>.</p>"
                f'<p><a href="{link}">Click here to set a new password</a></p>'
                f"<p>This link expires in {RESET_TOKEN_EXPIRE_MINUTES} minutes. "
                "If you did not request this, just ignore this email.</p>"
            )
            try:
                smtp_cfg = email_sender.SmtpConfig(**cfg)
                await asyncio.to_thread(
                    email_sender.send_one_sync,
                    smtp_cfg,
                    user.email,
                    "Password reset — B2B AI Lead Scraper",
                    html,
                )
                email_sent = True
            except Exception:
                log.exception("forgot-password email failed")
                email_sent = False
    return {"ok": True, "email_sent": email_sent}


@app.post("/api/v1/auth/reset-password")
def reset_password(body: ResetPasswordBody, db: Session = Depends(get_db)):
    user = _verify_reset_token(body.token, db)
    if not user:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This reset link is invalid, expired, or already used. Please request a new one.",
        )
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.pwd_reset_version = (user.pwd_reset_version or 0) + 1  # one-time: burn the link
    db.commit()
    return {"ok": True}


# --- Wizard ------------------------------------------------------------------------
# wizard_mod is imported lazily: wizard.py pulls httpx, which is only needed
# when the user actually tests an API key — not at server startup.
@app.post("/api/v1/wizard/test-openai")
async def wizard_test_openai(body: KeyTestBody, user: User = Depends(get_current_user)):
    from . import wizard as wizard_mod

    ok, message = await wizard_mod.test_openai_key(body.key.strip())
    return {"ok": ok, "message": message}


@app.post("/api/v1/wizard/test-apollo")
async def wizard_test_apollo(body: KeyTestBody, user: User = Depends(get_current_user)):
    from . import wizard as wizard_mod

    ok, message = await wizard_mod.test_apollo_key(body.key.strip())
    return {"ok": ok, "message": message}


@app.post("/api/v1/wizard/test-maps")
async def wizard_test_maps(body: KeyTestBody, user: User = Depends(get_current_user)):
    from . import wizard as wizard_mod

    ok, message = await wizard_mod.test_maps_key(body.key.strip())
    return {"ok": ok, "message": message}


@app.post("/api/v1/wizard/complete")
def wizard_complete(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = (
        db.query(Setting)
        .filter(Setting.user_id == user.id, Setting.key_name == "wizard_done")
        .first()
    )
    if row:
        row.encrypted_value = encrypt_value("1")
    else:
        db.add(Setting(user_id=user.id, key_name="wizard_done", encrypted_value=encrypt_value("1")))
    db.commit()
    return {"ok": True}


# --- Jobs --------------------------------------------------------------------------
def _job_out(job: Job) -> dict:
    return {
        "job_id": job.id,
        "industry": job.industry,
        "location": job.location,
        "max_leads": job.max_leads,
        "filters": job.filters or {},
        "status": job.status,
        "leads_found": job.leads_found,
        "sub_queries_run": job.sub_queries_run,
        "detail_calls": job.detail_calls,
        "apollo_credits_used": job.apollo_credits_used,
        "google_cost_usd": round(job.google_cost_usd, 4),
        "error_log": job.error_log or "",
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@app.get("/api/v1/jobs")
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = (
        db.query(Job)
        .filter(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .all()
    )
    return {"jobs": [_job_out(j) for j in jobs]}


@app.post("/api/v1/jobs", status_code=202)
async def create_job(
    body: JobCreateBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    # The Google Places key is mandatory — without it no real business data
    # exists to collect, and this product never fabricates leads. Fail fast
    # with a clear message instead of creating a job that is doomed to fail.
    keys = get_user_keys(db, user.id)
    if not keys.get("google_maps_key"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Add your Google Places API key in Settings → API Keys first. "
            "Search needs real business data and cannot run without it.",
        )

    job = Job(
        user_id=user.id,
        industry=body.industry.strip(),
        location=body.location.strip(),
        max_leads=body.max_leads,
        filters=body.filters,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    launch_job(job.id)
    return {"job_id": job.id, "status": "pending"}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return _job_out(job)


@app.delete("/api/v1/jobs/{job_id}")
def delete_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from .jobs import _running_tasks

    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    task = _running_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()
    db.delete(job)
    db.commit()
    return {"ok": True}


def _user_from_query_token(token: str | None, db: Session) -> User:
    # EventSource can't set Authorization headers — allow ?token= as fallback.
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user = db.query(User).filter(User.id == int(payload.get("sub"))).first()
    except (JWTError, TypeError, ValueError):
        user = None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


@app.get("/api/v1/jobs/{job_id}/stream")
async def stream_job(
    job_id: str,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = _user_from_query_token(token, db)
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return StreamingResponse(
        event_stream(job_id, user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/jobs/{job_id}/export")
def export_job(
    job_id: str,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    leads = db.query(Lead).filter(Lead.job_id == job_id).order_by(Lead.id).all()
    if format == "xlsx":
        content = export_xlsx(leads)
        media, ext = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    else:
        content = export_csv(leads)
        media, ext = "text/csv", "csv"
    filename = f"leads-{job_id[:8]}.{ext}"
    return StreamingResponse(
        iter([content]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/meta")
def get_meta():
    """Capability probe: tells the frontend whether it runs inside the
    desktop wrapper (pywebview) or a real browser. The launcher sets
    DESKTOP_APP=1; Docker/Railway deployments never do."""
    return {"desktop": os.environ.get("DESKTOP_APP") == "1", "version": APP_VERSION}


@app.post("/api/v1/jobs/{job_id}/export-disk")
def export_job_to_disk(
    job_id: str,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Desktop-app export path.

    pywebview (the native window) cannot trigger file downloads from JS —
    a programmatic <a download> click on a blob URL is silently swallowed,
    so the classic GET .../export flow produces no file there. For desktop
    clients the server writes the file straight to the user's Downloads
    folder and returns the path; the frontend shows it in a notice.
    Browser deployments keep using GET .../export (real download).
    """
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    leads = db.query(Lead).filter(Lead.job_id == job_id).order_by(Lead.id).all()
    content = export_xlsx(leads) if format == "xlsx" else export_csv(leads)
    ext = "xlsx" if format == "xlsx" else "csv"
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    base = f"leads-{job_id[:8]}"
    path = downloads / f"{base}.{ext}"
    n = 2
    while path.exists():
        path = downloads / f"{base}-{n}.{ext}"
        n += 1
    path.write_bytes(content)
    return {"path": str(path), "leads": len(leads), "format": ext}


# --- Settings ------------------------------------------------------------------------
def _mask(value: str) -> str:
    if not value:
        return ""
    return ("*" * max(0, len(value) - 4)) + value[-4:]


@app.get("/api/v1/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    keys = get_user_keys(db, user.id)
    done = (
        db.query(Setting)
        .filter(Setting.user_id == user.id, Setting.key_name == "wizard_done")
        .first()
    )
    return {
        "keys": {name: (_mask(keys[name]) if name in keys else None) for name in VALID_KEY_NAMES},
        "wizard_done": bool(done),
        "apollo_notice": (
            "Free Apollo keys include a limited monthly reveal pool (~75/mo per current "
            "reports — check your Apollo dashboard); Basic ($49/mo) unlocks full-volume "
            "decision-maker emails."
        ),
    }


@app.put("/api/v1/settings")
def put_settings(
    body: SettingsPutBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if body.key_name not in VALID_KEY_NAMES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"key_name must be one of {list(VALID_KEY_NAMES)}",
        )
    value = body.value.strip()
    if not value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "value must not be empty")
    row = (
        db.query(Setting)
        .filter(Setting.user_id == user.id, Setting.key_name == body.key_name)
        .first()
    )
    if row:
        row.encrypted_value = encrypt_value(value)
    else:
        db.add(
            Setting(
                user_id=user.id,
                key_name=body.key_name,
                encrypted_value=encrypt_value(value),
            )
        )
    db.commit()
    return {"ok": True, "key_name": body.key_name}


# --- Bulk email outreach (v3.2) ---------------------------------------------------
# Send ONE email (with optional {{name}}/{{company}}/{{title}} placeholders) to every
# lead in a job that has an email address — from inside the app, over the user's own
# SMTP account. Nothing routes through us, same as the Google/Apollo/OpenAI keys.
def _get_smtp_config(db: Session, user_id: int) -> dict | None:
    row = (
        db.query(Setting)
        .filter(Setting.user_id == user_id, Setting.key_name == SMTP_SETTING_KEY)
        .first()
    )
    if not row:
        return None
    try:
        return json.loads(decrypt_value(row.encrypted_value))
    except (ValueError, json.JSONDecodeError):
        return None


@app.get("/api/v1/email/smtp")
def get_smtp_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = _get_smtp_config(db, user.id)
    if not cfg:
        return {"configured": False}
    return {
        "configured": True,
        "host": cfg.get("host", ""),
        "port": cfg.get("port", 587),
        "username": cfg.get("username", ""),
        "from_email": cfg.get("from_email", ""),
        "from_name": cfg.get("from_name", ""),
        "use_tls": cfg.get("use_tls", True),
    }


@app.put("/api/v1/email/smtp")
def put_smtp_settings(
    body: SmtpConfigBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    cfg = body.model_dump()
    existing = _get_smtp_config(db, user.id)
    if existing and not cfg.get("password") and existing.get("password"):
        # The settings form loads with a blank password field; a blank submit
        # means "keep the saved password", not "erase it".
        cfg["password"] = existing["password"]
    row = (
        db.query(Setting)
        .filter(Setting.user_id == user.id, Setting.key_name == SMTP_SETTING_KEY)
        .first()
    )
    encrypted = encrypt_value(json.dumps(cfg))
    if row:
        row.encrypted_value = encrypted
    else:
        db.add(Setting(user_id=user.id, key_name=SMTP_SETTING_KEY, encrypted_value=encrypted))
    db.commit()
    return {"ok": True}


@app.post("/api/v1/email/test")
async def send_smtp_test(
    body: SmtpTestBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    cfg = _get_smtp_config(db, user.id)
    if not cfg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Save your SMTP settings first.")
    smtp_cfg = email_sender.SmtpConfig(**cfg)
    ok, message = await email_sender.send_test_email(smtp_cfg, body.to_email)
    return {"ok": ok, "message": message}


async def _run_campaign(campaign_id: str, smtp_cfg_dict: dict):
    db = next(get_db())
    try:
        campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
        if not campaign:
            return
        campaign.status = "running"
        db.commit()

        q = db.query(Lead).filter(Lead.job_id == campaign.job_id).filter(Lead.decision_maker_email != "")
        if campaign.only_valid_email:
            q = q.filter(Lead.email_status == "valid")
        leads = q.all()
        campaign.total = len(leads)
        db.commit()

        smtp_cfg = email_sender.SmtpConfig(**smtp_cfg_dict)

        async def on_progress(sent, failed):
            campaign.sent_count = sent
            campaign.failed_count = failed
            db.commit()

        sent, failed = await email_sender.send_bulk(
            smtp_cfg, campaign.subject, campaign.body_html, leads, on_progress=on_progress
        )
        campaign.sent_count = sent
        campaign.failed_count = failed
        campaign.status = "completed"
        campaign.finished_at = datetime.datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("bulk email campaign %s failed", campaign_id)
        campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
        if campaign:
            campaign.status = "failed"
            campaign.error_log = str(exc)[:1000]
            campaign.finished_at = datetime.datetime.utcnow()
            db.commit()
    finally:
        db.close()


@app.post("/api/v1/jobs/{job_id}/bulk-email", status_code=202)
async def start_bulk_email(
    job_id: str,
    body: BulkEmailBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    cfg = _get_smtp_config(db, user.id)
    if not cfg:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Add your SMTP (email sending) settings first — Settings → Bulk Email.",
        )
    q = db.query(Lead).filter(Lead.job_id == job_id, Lead.decision_maker_email != "")
    if body.only_valid_email:
        q = q.filter(Lead.email_status == "valid")
    eligible = q.count()
    if eligible == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No leads with an email address match your filter for this job.",
        )
    campaign = EmailCampaign(
        job_id=job_id,
        user_id=user.id,
        subject=body.subject,
        body_html=body.body_html,
        only_valid_email=body.only_valid_email,
        status="pending",
        total=eligible,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    asyncio.create_task(_run_campaign(campaign.id, cfg))
    return {"campaign_id": campaign.id, "total": eligible}


@app.get("/api/v1/email/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    campaign = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.id == campaign_id, EmailCampaign.user_id == user.id)
        .first()
    )
    if not campaign:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found.")
    return {
        "id": campaign.id,
        "job_id": campaign.job_id,
        "status": campaign.status,
        "total": campaign.total,
        "sent_count": campaign.sent_count,
        "failed_count": campaign.failed_count,
        "error_log": campaign.error_log,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "finished_at": campaign.finished_at.isoformat() if campaign.finished_at else None,
    }


@app.get("/api/v1/jobs/{job_id}/email-eligible-count")
def email_eligible_count(
    job_id: str,
    only_valid_email: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    q = db.query(Lead).filter(Lead.job_id == job_id, Lead.decision_maker_email != "")
    if only_valid_email:
        q = q.filter(Lead.email_status == "valid")
    return {"eligible": q.count()}


# --- Dashboard ------------------------------------------------------------------------
@app.get("/api/v1/dashboard/stats")
def dashboard_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total_leads = (
        db.query(func.count(Lead.id))
        .join(Job, Lead.job_id == Job.id)
        .filter(Job.user_id == user.id)
        .scalar()
        or 0
    )
    tiers = (
        db.query(Lead.enrichment_status, func.count(Lead.id))
        .join(Job, Lead.job_id == Job.id)
        .filter(Job.user_id == user.id)
        .group_by(Lead.enrichment_status)
        .all()
    )
    tier_counts = {"full": 0, "company": 0, "basic": 0}
    for status_, count in tiers:
        if status_ in tier_counts:
            tier_counts[status_] = count
    credits = (
        db.query(func.coalesce(func.sum(Job.apollo_credits_used), 0))
        .filter(Job.user_id == user.id)
        .scalar()
        or 0
    )
    cost = (
        db.query(func.coalesce(func.sum(Job.google_cost_usd), 0.0))
        .filter(Job.user_id == user.id)
        .scalar()
        or 0.0
    )
    total_jobs = (
        db.query(func.count(Job.id)).filter(Job.user_id == user.id).scalar() or 0
    )
    return {
        "total_leads": total_leads,
        "full_count": tier_counts["full"],
        "company_count": tier_counts["company"],
        "basic_count": tier_counts["basic"],
        "apollo_credits_used": int(credits),
        "google_cost_usd": round(float(cost), 4),
        "total_jobs": total_jobs,
    }


@app.get("/api/v1/dashboard/recent")
def dashboard_recent(
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(Job)
        .filter(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "recent": [
            {
                "job_id": j.id,
                "industry": j.industry,
                "location": j.location,
                "status": j.status,
                "leads_found": j.leads_found,
                "max_leads": j.max_leads,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ]
    }


# --- Health ------------------------------------------------------------------------
@app.get("/api/v1/health")
def health():
    # "app" marker lets the desktop launcher tell OUR server apart from any
    # other program squatting on the same port (singleton check).
    return {"status": "ok", "app": "leadscraper"}


# --- Serve the built frontend (single-container deploy) ---------------------------
# Set FRONTEND_DIST to the Vite dist dir (Dockerfile does this). API routes are
# registered above, so this catch-all only serves the SPA for non-API paths.
if os.path.isdir(FRONTEND_DIST):
    _assets = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
