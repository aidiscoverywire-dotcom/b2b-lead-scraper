"""Google Places API (New) client — query fan-out + async details.

No googlemaps SDK anywhere: direct REST via httpx.AsyncClient with explicit
X-Goog-Api-Key + X-Goog-FieldMask headers on every call (blueprint 7.1).
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable

import httpx

# NOTE: phonenumbers is imported lazily inside normalize_phone — it is only
# needed while a job runs, not at server startup.
from .net import async_client as http_client
from .config import (
    COST_PER_DETAIL_CALL,
    COST_PER_SEARCH_PAGE,
    DETAIL_CONCURRENCY,
    PLACES_BASE,
    PLACES_SEARCH_URL,
    SEARCH_MAX_PAGES,
    SEARCH_PAGE_SIZE,
)

log = logging.getLogger(__name__)

# --- Field masks (explicit on every call) ------------------------------------
# Search: IDs only. Our detail mask triggers Place Details Enterprise SKU
# ($20/1k, 1,000 free/mo) — Google bills every request at the highest tier
# of any requested field (verified Sep 2026).
SEARCH_FIELD_MASK = "places.id,places.displayName"
DETAIL_FIELD_MASK = (
    "id,displayName,formattedAddress,addressComponents,"
    "internationalPhoneNumber,websiteUri,rating,userRatingCount,types"
)


class PlacesError(Exception):
    """Raised for Places API failures that should surface to the user."""

    def __init__(self, message: str, kind: str = "places_error"):
        super().__init__(message)
        self.kind = kind  # api_not_enabled | rate_limited | bad_request | http


# --- Sub-query fan-out ---------------------------------------------------------
# Contract: >=8 distinct textQueries per (industry, location); stop early when
# the place_id set reaches max_leads. Exact variation list is implementation
# detail (blueprint 7.1).
_INDUSTRY_SYNONYMS: dict[str, list[str]] = {
    "restaurant": ["restaurants", "dining", "eatery"],
    "hotel": ["hotels", "lodging", "accommodation"],
    "dentist": ["dentists", "dental clinic", "dental care"],
    "lawyer": ["lawyers", "law firm", "attorney"],
    "plumber": ["plumbers", "plumbing service"],
    "electrician": ["electricians", "electrical contractor"],
    "gym": ["gyms", "fitness center", "health club"],
    "salon": ["salons", "beauty salon", "hair salon"],
    "cafe": ["cafes", "coffee shop", "coffeehouse"],
    "bar": ["bars", "pub", "cocktail bar"],
    "pharmacy": ["pharmacies", "drugstore"],
    "clinic": ["clinics", "medical clinic"],
    "school": ["schools", "academy"],
    "car dealer": ["car dealers", "auto dealer", "car dealership"],
    "real estate": ["real estate agency", "realtor", "property agency"],
}


def _plural(word: str) -> str:
    if word.lower().endswith("y") and word[-2:-1].lower() not in "aeiou":
        return word[:-1] + "ies"
    if word.lower().endswith("s"):
        return word
    return word + "s"


def _synonyms(industry: str) -> list[str]:
    key = industry.strip().lower()
    raw = industry.strip()
    syns: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        if s.lower() not in seen:
            seen.add(s.lower())
            syns.append(s)

    # table hits for the key as given, plus its singular/plural variant —
    # so "dentists" also picks up the "dentist" synonym row (and vice versa)
    cands = [key]
    if key.endswith("s") and len(key) > 3:
        cands.append(key[:-1])
    else:
        cands.append(_plural(key))
    for cand in cands:
        for s in _INDUSTRY_SYNONYMS.get(cand, []):
            add(s)
    add(raw)  # the user's own wording, always included
    if raw.lower().endswith("s") and len(raw) > 3:
        add(raw[:-1])  # singular variant
    else:
        add(_plural(raw))  # plural variant
    return syns


def build_subqueries(industry: str, location: str) -> list[str]:
    """8-10 distinct textQuery variations: industry synonyms x query templates."""
    templates = [
        "{i} in {l}",
        "{i} company in {l}",
        "{i} services in {l}",
        "{i} firm in {l}",
        "best {i} in {l}",
    ]
    queries: list[str] = []
    for syn in _synonyms(industry):
        for tmpl in templates:
            q = tmpl.format(i=syn, l=location.strip())
            if q not in queries:
                queries.append(q)
            if len(queries) >= 10:
                return queries
    return queries  # >=8 guaranteed by templates x synonyms


# --- Low-level request helpers -------------------------------------------------
def _headers(key: str, mask: str) -> dict[str, str]:
    return {"X-Goog-Api-Key": key, "X-Goog-FieldMask": mask}


def _map_http_error(status: int, body: str) -> PlacesError:
    if status == 403:
        return PlacesError(
            "Places API (New) is not enabled for this key. In Google Cloud Console, "
            "enable 'Places API (New)' (not the legacy Places API) and retry.",
            kind="api_not_enabled",
        )
    if status == 400:
        return PlacesError(
            f"Places API rejected the request (400): {body[:200]}",
            kind="bad_request",
        )
    return PlacesError(f"Places API HTTP {status}: {body[:200]}", kind="http")


async def _post_search_page(
    client: httpx.AsyncClient,
    key: str,
    text_query: str,
    page_token: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"textQuery": text_query, "pageSize": SEARCH_PAGE_SIZE}
    if page_token:
        payload["pageToken"] = page_token
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0, 1, 2, 4]):  # first try + 3 backoff retries
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.post(
                PLACES_SEARCH_URL, headers=_headers(key, SEARCH_FIELD_MASK),
                json=payload, timeout=30,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            continue
        if resp.status_code == 429:
            last_exc = PlacesError("rate limited", kind="rate_limited")
            continue  # backoff and retry
        if resp.status_code != 200:
            raise _map_http_error(resp.status_code, resp.text)
        return resp.json()
    raise PlacesError(
        f"Places Text Search rate-limited after 3 retries (query: {text_query!r}). "
        "Marked failed; run continues with partial results.",
        kind="rate_limited",
    ) from last_exc


async def _get_detail(
    client: httpx.AsyncClient,
    key: str,
    place_id: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any] | None:
    url = f"{PLACES_BASE}/places/{place_id}"
    async with sem:
        for delay in [0, 1, 2, 4]:
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await client.get(
                    url, headers=_headers(key, DETAIL_FIELD_MASK), timeout=30
                )
            except httpx.HTTPError:
                continue
            if resp.status_code == 429:
                continue
            if resp.status_code == 403:
                raise _map_http_error(403, resp.text)
            if resp.status_code != 200:
                log.warning("detail %s -> HTTP %s, skipped", place_id, resp.status_code)
                return None
            return resp.json()
    log.warning("detail %s rate-limited after retries, skipped", place_id)
    return None


# --- Public API -----------------------------------------------------------------
async def search_places(
    key: str,
    industry: str,
    location: str,
    max_leads: int,
    on_page: Callable[[int], Awaitable[None]] | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, str]]:
    """Fan-out search. Returns [{place_id, name}] deduped across sub-queries.

    Stops when max_leads unique place_ids are collected. If all sub-queries
    exhaust below max_leads, returns what was found — the caller completes
    gracefully ('Found N of M requested'), never fabricates leads.
    `on_page` is awaited once per billed search page (cost accounting).
    Pass `client` to reuse one connection pool across the whole job; otherwise
    a short-lived client is created.
    """
    if client is not None:
        return await _search_with(client, key, industry, location, max_leads, on_page)
    async with http_client() as client:
        return await _search_with(client, key, industry, location, max_leads, on_page)


async def _search_with(
    client: httpx.AsyncClient,
    key: str,
    industry: str,
    location: str,
    max_leads: int,
    on_page: Callable[[int], Awaitable[None]] | None,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for query in build_subqueries(industry, location):
        if len(results) >= max_leads:
            break
        page_token: str | None = None
        for _ in range(SEARCH_MAX_PAGES):
            try:
                data = await _post_search_page(client, key, query, page_token)
            except PlacesError as exc:
                if exc.kind == "api_not_enabled":
                    raise
                # bad_request / rate_limited-exhausted: mark query failed, continue
                log.warning("sub-query %r failed (%s); continuing", query, exc)
                break
            if on_page is not None:
                await on_page(1)
            for place in data.get("places", []):
                pid = place.get("id") or ""
                if pid and pid not in seen:
                    seen.add(pid)
                    name = (place.get("displayName") or {}).get("text", "")
                    results.append({"place_id": pid, "name": name})
                    if len(results) >= max_leads:
                        break
            page_token = data.get("nextPageToken")
            if not page_token or len(results) >= max_leads:
                break
    return results


def _map_detail(place_id: str, data: dict[str, Any]) -> dict[str, Any]:
    addr_comps = data.get("addressComponents") or []
    region = ""
    for comp in addr_comps:
        if "country" in (comp.get("types") or []):
            region = comp.get("shortText", "")
            break
    return {
        "place_id": place_id,
        "name": (data.get("displayName") or {}).get("text", ""),
        "address": data.get("formattedAddress", ""),
        "phone_raw": data.get("internationalPhoneNumber", ""),
        "region": region,
        "website": data.get("websiteUri", ""),
        "rating": data.get("rating"),
        "review_count": data.get("userRatingCount"),
        "types": data.get("types") or [],
    }


async def get_place_details(
    key: str,
    place_ids: list[str],
    on_detail: Callable[[], Awaitable[None]] | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch details for each place_id with asyncio.Semaphore(10).

    `on_detail` is awaited once per billed detail call (cost accounting).
    Individual failures are skipped — never crash the run.
    Pass `client` to reuse one connection pool (one client per job instead
    of one per place_id).
    """
    if client is not None:
        return await _details_with(client, key, place_ids, on_detail)
    async with http_client() as client:
        return await _details_with(client, key, place_ids, on_detail)


async def _details_with(
    client: httpx.AsyncClient,
    key: str,
    place_ids: list[str],
    on_detail: Callable[[], Awaitable[None]] | None,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(DETAIL_CONCURRENCY)
    out: list[dict[str, Any]] = []

    async def one(pid: str):
        try:
            data = await _get_detail(client, key, pid, sem)
        except PlacesError as exc:
            if exc.kind == "api_not_enabled":
                raise
            return
        if data is None:
            return
        if on_detail is not None:
            await on_detail()
        out.append(_map_detail(pid, data))

    # run in controlled batches so one 403 aborts cleanly
    for i in range(0, len(place_ids), DETAIL_CONCURRENCY * 5):
        batch = place_ids[i : i + DETAIL_CONCURRENCY * 5]
        await asyncio.gather(*(one(pid) for pid in batch))
    return out


# --- Phone normalization (blueprint 7.3) -----------------------------------------
def normalize_phone(phone_raw: str, region: str) -> str:
    """Return E.164 when parseable, else the raw value (caller may flag it)."""
    import phonenumbers  # lazy: only needed while a job runs

    if not phone_raw:
        return ""
    try:
        if phone_raw.strip().startswith("+"):
            num = phonenumbers.parse(phone_raw, None)
        else:
            num = phonenumbers.parse(phone_raw, region or None)
        if phonenumbers.is_possible_number_with_reason(num) == phonenumbers.ValidationResult.IS_POSSIBLE:
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        return phone_raw
    except Exception:
        return phone_raw
