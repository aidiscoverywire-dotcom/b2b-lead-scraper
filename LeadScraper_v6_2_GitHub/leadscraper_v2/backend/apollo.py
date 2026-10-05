"""Apollo.io enrichment — honest three-tier model (blueprint 7.2).

- enrich_organization: 0 credits, works on free keys (per current reports).
- match_person: 1 credit per matched person. TRY-FIRST logic: always attempt
  when the buyer enables enrichment (free keys carry ~75 reveal credits/month
  per 2026 reports) — on 402/403 degrade gracefully, never crash, never assume.
- enrich_lead: 'basic' | 'company' | 'full'. Emails come ONLY from
  people/match responses — never invented.
"""
import logging
from urllib.parse import urlparse

import httpx

from .config import APOLLO_BASE
from .net import async_client as http_client

log = logging.getLogger(__name__)

_SENIORITIES = ["founder", "c_level", "vp", "director"]


class ApolloBlocked(Exception):
    """402/403 from Apollo — degrade the tier, don't crash the run."""


def extract_domain(website: str) -> str:
    if not website:
        return ""
    url = website if "://" in website else f"https://{website}"
    host = urlparse(url).hostname or ""
    return host.lower().lstrip("www.").strip(".")


async def enrich_organization(key: str, domain: str, client=None) -> dict | None:
    """POST /v1/organizations/enrich. Returns {company_size, industry} or None.

    Skips (returns None) when there is no domain — the API would 422.
    Raises ApolloBlocked on 402/403.
    Pass `client` to reuse one connection pool across the whole job.
    """
    if not domain:
        return None
    if client is None:
        async with http_client() as client:
            return await _enrich_org(client, key, domain)
    return await _enrich_org(client, key, domain)


async def _enrich_org(client: httpx.AsyncClient, key: str, domain: str) -> dict | None:
    resp = await client.post(
        f"{APOLLO_BASE}/organizations/enrich",
        headers={"x-api-key": key, "Content-Type": "application/json"},
        json={"domain": domain},
        timeout=30,
    )
    if resp.status_code in (402, 403):
        raise ApolloBlocked(f"organizations/enrich blocked ({resp.status_code})")
    if resp.status_code == 422:
        return None  # no org data for this domain — skip, don't crash
    if resp.status_code != 200:
        log.warning("organizations/enrich %s -> HTTP %s", domain, resp.status_code)
        return None
    org = (resp.json() or {}).get("organization") or {}
    size = org.get("estimated_num_employees")
    return {
        "company_size": str(size) if size else "",
        "industry": org.get("industry") or "",
    }


async def match_person(key: str, domain: str, company_name: str = "", client=None) -> dict | None:
    """POST /v1/people/match. Returns {name, title, email} or None.

    Always attempted when enrichment is enabled (try-first). Raises
    ApolloBlocked on 402/403 so the caller can degrade the tier.
    Pass `client` to reuse one connection pool across the whole job.
    """
    if not domain:
        return None
    if client is None:
        async with http_client() as client:
            return await _match_person(client, key, domain, company_name)
    return await _match_person(client, key, domain, company_name)


async def _match_person(
    client: httpx.AsyncClient, key: str, domain: str, company_name: str
) -> dict | None:
    payload: dict = {
        "domain": domain,
        "seniorities": _SENIORITIES,
        "reveal_personal_emails": False,
    }
    if company_name:
        payload["q_organization_name"] = company_name
    resp = await client.post(
        f"{APOLLO_BASE}/people/match",
        headers={"x-api-key": key, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code in (402, 403):
        raise ApolloBlocked(f"people/match blocked ({resp.status_code})")
    if resp.status_code != 200:
        log.warning("people/match %s -> HTTP %s", domain, resp.status_code)
        return None
    person = (resp.json() or {}).get("person") or {}
    email = person.get("email") or ""
    if not person or not email:
        return None  # no reveal — no credit-worthy result
    return {
        "name": person.get("name") or "",
        "title": person.get("title") or "",
        "email": email,
    }


async def enrich_lead(
    key: str | None,
    lead: dict,
    enrichment_enabled: bool = True,
    client=None,
) -> tuple[str, dict, int, str]:
    """Enrich one lead. Returns (status, data, credits_used, note).

    status in {'basic','company','full'}. Never invents emails.
    402/403 anywhere -> degrade + note (caller logs to jobs.error_log).
    """
    data: dict = {}
    if not key or not enrichment_enabled:
        return "basic", data, 0, ""
    domain = extract_domain(lead.get("website", ""))

    # 1) org enrich (0 credits) -> at least 'company'
    status = "basic"
    try:
        org = await enrich_organization(key, domain, client=client)
    except ApolloBlocked as exc:
        return "basic", data, 0, f"apollo org enrich blocked: {exc}"
    if org:
        status = "company"
        data.update(org)

    # 2) people/match (1 credit) -> 'full' — try first, degrade on block
    credits = 0
    try:
        person = await match_person(key, domain, lead.get("name", ""), client=client)
    except ApolloBlocked as exc:
        note = f"apollo people/match blocked: {exc}"
        return status, data, credits, note
    if person:
        status = "full"
        data.update(
            {
                "decision_maker_name": person["name"],
                "decision_maker_title": person["title"],
                "decision_maker_email": person["email"],
            }
        )
        credits = 1
    return status, data, credits, ""
