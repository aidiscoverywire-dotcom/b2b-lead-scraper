"""AI pitch + lead score via gpt-4o-mini (blueprint: ai_pitch.py).

3-retry cap. Any failure degrades to an empty pitch (and no score) —
it never fails the run.
"""
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only — never imported at runtime
    from openai import AsyncOpenAI

# NOTE: `openai` is imported lazily inside create_client — it is the single
# slowest third-party import (~0.5s) and is only needed while a job with an
# OpenAI key runs, never at server startup.
from .net import async_client as http_client

log = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_RETRIES = 3

_SYSTEM = (
    "You write short B2B outreach pitches. Reply with ONLY a JSON object: "
    '{"pitch": "<2-3 sentence personalized pitch>", "score": <0-100 lead quality score>}. '
    "No markdown, no extra text."
)


def _prompt(lead: dict) -> str:
    return (
        "Write a 2-3 sentence personalized outreach pitch and a 0-100 lead score for:\n"
        f"- Business: {lead.get('name', '')}\n"
        f"- Industry: {lead.get('industry', '')}\n"
        f"- Address: {lead.get('address', '')}\n"
        f"- Rating: {lead.get('rating', '')} ({lead.get('review_count', '')} reviews)\n"
        f"- Website: {lead.get('website', '')}\n"
    )


def create_client(openai_key: str):
    """Build one shared AsyncOpenAI client per job (not one per lead)."""
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=openai_key, http_client=http_client())


async def generate_pitch_and_score(
    openai_key: str, lead: dict, client=None
) -> tuple[str, float | None]:
    """Returns (pitch, score). On any failure -> ("", None).

    Pass a shared `client` (from create_client) to reuse one connection pool
    across the whole job; otherwise a short-lived client is created.
    """
    if not openai_key:
        return "", None
    if client is not None:
        return await _generate(client, lead)
    client = create_client(openai_key)
    try:
        return await _generate(client, lead)
    finally:
        await client.close()


async def _generate(
    client: "AsyncOpenAI", lead: dict
) -> tuple[str, float | None]:
    """Returns (pitch, score). On any failure -> ("", None)."""
    last_exc: Exception | None = None
    for _ in range(_MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _prompt(lead)},
                ],
                max_tokens=220,
                temperature=0.7,
                timeout=30,
            )
            text = (resp.choices[0].message.content or "").strip()
            data = json.loads(text)
            pitch = str(data.get("pitch", "")).strip()
            score = data.get("score")
            score = float(score) if isinstance(score, (int, float)) else None
            if score is not None:
                score = max(0.0, min(100.0, score))
            return pitch, score
        except Exception as exc:  # noqa: BLE001 — degrade, never fail the run
            last_exc = exc
            log.warning("gpt-4o-mini pitch failed: %s", exc)
    log.error("gpt-4o-mini pitch failed after %d retries: %s", _MAX_RETRIES, last_exc)
    return "", None
