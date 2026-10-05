"""SQLAlchemy models + SQLite engine (WAL mode).

No in-memory job store anywhere: the SSE stream and resume-after-restart
read job state from the jobs table (blueprint 5).
"""
import datetime
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import DB_PATH


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # True for the auto-seeded admin/123 account until the password is changed.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Bumped on every password change — outstanding reset tokens embed the
    # version they were issued for, so each link is one-time.
    pwd_reset_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="user", cascade="all, delete-orphan")


class Setting(Base):
    """Exactly 3 rows per user: openai_key, apollo_key, google_maps_key.
    Values are Fernet-encrypted (see crypto.py). No proxy_url — removed in v3.1."""

    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("user_id", "key_name", name="uq_settings_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    key_name: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Job(Base):
    """Replaces the old in-memory jobs dict. SSE stream and resume-after-restart
    read from this table."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    industry: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    max_leads: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # pending -> running -> completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    leads_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sub_queries_run: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    apollo_credits_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    google_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_log: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="jobs")
    leads: Mapped[list["Lead"]] = relationship(
        "Lead", back_populates="job", cascade="all, delete-orphan"
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False, index=True
    )
    place_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("job_id", "place_id", name="uq_lead_job_place"),
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    rating: Mapped[float] = mapped_column(Float, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=True)
    types: Mapped[str] = mapped_column(Text, nullable=False, default="")  # comma-joined
    # enrichment_status in {basic, company, full}
    enrichment_status: Mapped[str] = mapped_column(String(16), nullable=False, default="basic")
    company_size: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    company_industry: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    decision_maker_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    decision_maker_title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    decision_maker_email: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # email_status in {valid, invalid, unknown}
    email_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    pitch: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lead_score: Mapped[float] = mapped_column(Float, nullable=True)
    # --- Bulk outreach (v3.2) ------------------------------------------
    # campaign_email_status in {not_sent, sent, failed, skipped}
    campaign_email_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_sent"
    )
    campaign_email_sent_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    campaign_email_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship("Job", back_populates="leads")


class EmailCampaign(Base):
    """A bulk-send run against one job's leads (v3.2 — in-app outreach)."""

    __tablename__ = "email_campaigns"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    only_valid_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # pending -> running -> completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_log: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)


def _enable_wal(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.close()


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)
event.listen(engine, "connect", _enable_wal)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _migrate_sqlite() -> None:
    """Add columns/tables introduced after the initial release.

    No Alembic in this project (blueprint keeps it dependency-light) — this
    is a hand-rolled, additive-only migration safe to run on every startup.
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(leads)")}
        if "campaign_email_status" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE leads ADD COLUMN campaign_email_status VARCHAR(16) "
                "NOT NULL DEFAULT 'not_sent'"
            )
        if "campaign_email_sent_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE leads ADD COLUMN campaign_email_sent_at DATETIME")
        if "campaign_email_error" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE leads ADD COLUMN campaign_email_error TEXT NOT NULL DEFAULT ''"
            )
        user_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        if "must_change_password" not in user_cols:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"
            )
        if "pwd_reset_version" not in user_cols:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN pwd_reset_version INTEGER NOT NULL DEFAULT 0"
            )


def init_db() -> None:
    """Create tables (lightweight startup migration)."""
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
