"""
Grants.gov Live Feed — Layer 3 of TractPitch grant enrichment.

For each matched grant, fetches the nearest open solicitation from the
Grants.gov search2 API (no key required).

Strategy:
  1. Formula grants (block grants distributed by state formula) → return
     {formula: True} immediately; they never post individual solicitations.
  2. State-specific grants (no CFDA) → return None; not on Grants.gov.
  3. CFDA-only search first (most precise).
  4. Keyword fallback: search by shortened program name, then filter results
     in-code to only those whose cfdaList includes our program number.
  5. Cache results in-memory for CACHE_TTL seconds per (program_number).
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRANTS_GOV_URL = "https://api.grants.gov/v1/api/search2"
CACHE_TTL = 3600  # 1 hour

# Formula / block grants distributed through state/local entitlement formulas.
# These never post individual competitive solicitations on Grants.gov.
FORMULA_CFDAS: set[str] = {
    "14.218",  # Community Development Block Grant (CDBG)
    "14.239",  # HOME Investment Partnerships
    "84.010",  # Title I Part A — Improving Basic Programs
    "17.258",  # WIOA Adult Employment and Training
}

# Cache: program_number → (timestamp, result)
_cache: dict[str, tuple[float, Optional[dict]]] = {}


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _get_cached(key: str) -> tuple[bool, Optional[dict]]:
    if key in _cache:
        ts, val = _cache[key]
        if time.monotonic() - ts < CACHE_TTL:
            return True, val
    return False, None


def _put_cache(key: str, val: Optional[dict]) -> None:
    _cache[key] = (time.monotonic(), val)


# ── API helpers ───────────────────────────────────────────────────────────────

def _search(payload: dict) -> list[dict]:
    """POST to Grants.gov search2 and return oppHits list."""
    try:
        resp = httpx.post(GRANTS_GOV_URL, json=payload, timeout=8.0)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("oppHits", [])
    except Exception as exc:
        logger.warning("Grants.gov API error: %s", exc)
        return []


def _pick_best(hits: list[dict]) -> Optional[dict]:
    """
    Choose the best solicitation from a list of oppHits.
    Preference: posted with closeDate first, then posted without, then forecasted.
    Within each tier, sort by nearest closeDate.
    """
    posted_dated    = [h for h in hits if h.get("oppStatus") == "posted" and h.get("closeDate")]
    posted_open     = [h for h in hits if h.get("oppStatus") == "posted" and not h.get("closeDate")]
    forecasted      = [h for h in hits if h.get("oppStatus") == "forecasted"]

    def by_close(h: dict) -> datetime:
        cd = h.get("closeDate", "")
        try:
            return datetime.strptime(cd, "%m/%d/%Y")
        except ValueError:
            return datetime(9999, 12, 31)

    if posted_dated:
        return sorted(posted_dated, key=by_close)[0]
    if posted_open:
        return posted_open[0]
    if forecasted:
        return forecasted[0]
    return None


def _format_hit(hit: dict) -> dict:
    close_date = hit.get("closeDate") or None
    return {
        "title":    hit.get("title"),
        "deadline": close_date,
        "url":      f"https://www.grants.gov/search-results-detail/{hit['id']}",
        "status":   hit.get("oppStatus"),   # "posted" | "forecasted"
    }


def _keyword_for(program_name: str) -> str:
    """
    Strip parentheticals and take the first 5 words as a search keyword.
    E.g. "EPA Brownfields Assessment Grants (66.818)" → "EPA Brownfields Assessment Grants"
    """
    clean = re.sub(r"\([^)]*\)", "", program_name).strip()
    words = clean.split()[:5]
    return " ".join(words)


# ── Public interface ──────────────────────────────────────────────────────────

def fetch_solicitation(program_name: str, program_number: Optional[str]) -> Optional[dict]:
    """
    Fetch the nearest open Grants.gov solicitation for a given grant program.

    Returns one of:
        {"formula": True}                              — formula/block grant
        {"title", "deadline", "url", "status"}        — active solicitation found
        None                                           — no result
    """
    # Formula grants: no competitive solicitation posted
    if program_number in FORMULA_CFDAS:
        return {"formula": True}

    # State grants and grants without a CFDA number: skip
    if not program_number:
        return None

    # Cache check
    hit, cached = _get_cached(program_number)
    if hit:
        return cached

    result: Optional[dict] = None

    # Pass 1 — CFDA-only (most precise)
    hits = _search({
        "cfda": program_number,
        "oppStatuses": "forecasted|posted",
        "rows": 10,
        "startRecordNum": 0,
    })
    best = _pick_best(hits)
    if best:
        result = _format_hit(best)

    # Pass 2 — keyword fallback, filtered to matching CFDA in results
    if result is None:
        keyword = _keyword_for(program_name)
        hits = _search({
            "keyword": keyword,
            "oppStatuses": "forecasted|posted",
            "rows": 20,
            "startRecordNum": 0,
        })
        # Only keep hits that explicitly list our CFDA number
        hits = [h for h in hits if program_number in (h.get("cfdaList") or [])]
        best = _pick_best(hits)
        if best:
            result = _format_hit(best)

    _put_cache(program_number, result)
    return result
