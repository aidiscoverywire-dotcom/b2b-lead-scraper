"""3-step setup wizard key tests (blueprint Phase 2).

1. OpenAI key  -> GET https://api.openai.com/v1/models (1 page)
2. Apollo key  -> POST /v1/organizations/enrich {domain: 'apollo.io'} (0 credits)
                 + honest tier notice (free pool ~75/mo per reports, Basic $49/mo)
3. Google key  -> POST places:searchText {textQuery:'Eiffel Tower', pageSize:1}
                 with X-Goog-FieldMask 'places.id' — tests exactly the API the
                 product uses. NO proxy step (removed in v3.1).
"""
import httpx

from .apollo import ApolloBlocked, enrich_organization
from .config import APOLLO_FREE_MONTHLY_POOL, OPENAI_MODELS_URL, PLACES_SEARCH_URL
from .net import async_client as http_client

_TIER_NOTICE = (
    "Apollo enrichment is 3-tier: with reveal credits available you get decision-maker "
    "emails ('full'); otherwise company data only ('company'). Free keys include a "
    f"limited monthly reveal pool (~{APOLLO_FREE_MONTHLY_POOL}/mo per current reports — "
    "verify in your Apollo dashboard); Apollo Basic ($49/mo) unlocks full-volume emails. "
    "Without Apollo, the tool still returns full Google business data."
)


async def test_openai_key(key: str) -> tuple[bool, str]:
    if not key:
        return False, "No key provided."
    try:
        async with http_client() as client:
            resp = await client.get(
                OPENAI_MODELS_URL,
                headers={"Authorization": f"Bearer {key}"},
                timeout=20,
            )
    except httpx.HTTPError as exc:
        return False, f"Network error: {exc}"
    if resp.status_code == 200:
        return True, "OpenAI key works."
    if resp.status_code == 401:
        return False, "Invalid OpenAI key (401)."
    return False, f"OpenAI returned HTTP {resp.status_code}."


async def test_apollo_key(key: str) -> tuple[bool, str]:
    """Wizard test: org enrich on 'apollo.io' — 0 credits, proves the key works
    on a free plan too."""
    if not key:
        return False, "No key provided (Apollo is optional — you can skip this step)."
    try:
        org = await enrich_organization(key, "apollo.io")
    except ApolloBlocked:
        return True, (
            "Key is valid but enrichment is blocked on this plan (402/403). "
            + _TIER_NOTICE
        )
    except httpx.HTTPError as exc:
        return False, f"Network error: {exc}"
    if org is None:
        # Could be a 401 wrapped as None only for 422/4xx — re-check explicitly
        async with http_client() as client:
            resp = await client.post(
                "https://api.apollo.io/v1/organizations/enrich",
                headers={"x-api-key": key, "Content-Type": "application/json"},
                json={"domain": "apollo.io"},
                timeout=20,
            )
        if resp.status_code == 401:
            return False, "Invalid Apollo key (401)."
        return False, f"Apollo returned HTTP {resp.status_code}."
    return True, "Apollo key works. " + _TIER_NOTICE


async def test_maps_key(key: str) -> tuple[bool, str]:
    if not key:
        return False, "No key provided."
    try:
        async with http_client() as client:
            resp = await client.post(
                PLACES_SEARCH_URL,
                headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.id"},
                json={"textQuery": "Eiffel Tower", "pageSize": 1},
                timeout=20,
            )
    except httpx.HTTPError as exc:
        return False, f"Network error: {exc}"
    if resp.status_code == 200:
        return True, "Google Maps key works with Places API (New)."
    if resp.status_code == 403:
        return False, (
            "Places API (New) is not enabled for this key. In Google Cloud Console, "
            "enable 'Places API (New)' (not the legacy Places API) and retry."
        )
    if resp.status_code == 400:
        return False, f"Request rejected (400): {resp.text[:200]}"
    return False, f"Google returned HTTP {resp.status_code}."
