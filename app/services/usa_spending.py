"""
USASpending Historical Awards — Layer 4 of TractPitch grant enrichment.

Fetches federal grant awards placed in the same county as the given census
tract, covering the last 3 fiscal years.

NOTE: The USASpending API does not support census-tract-level place-of-
performance filtering. The finest geographic filter available is county
(state + county FIPS). Results are scoped to the full county, not the
individual tract.

Two API calls per lookup:
  1. spending_by_category/awarding_agency/ — total awarded + agency breakdown
  2. spending_by_award/                    — top 5 individual awards by amount

Results are cached in-memory for 24 hours (one entry per state+county pair,
shared across all tracts in the same county).
"""

import logging
import time
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL    = "https://api.usaspending.gov/api/v2"
CACHE_TTL   = 86_400   # 24 hours
AWARD_TYPES = ["02", "03", "04", "05"]   # grants only

# In-memory cache: (state_fips, county_fips) → (timestamp, result)
_cache: dict[tuple[str, str], tuple[float, Optional[dict]]] = {}

# ── FIPS → state abbreviation ─────────────────────────────────────────────────

_STATE_ABBR: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY",
}

# Known county names for our target metros (to humanise the UI label)
_COUNTY_NAMES: dict[tuple[str, str], str] = {
    ("27", "053"): "Hennepin County",
    ("27", "123"): "Ramsey County",
    ("27", "037"): "Dakota County",
    ("27", "003"): "Anoka County",
    ("27", "163"): "Washington County",
    ("27", "139"): "Scott County",
    ("27", "019"): "Carver County",
    ("19", "163"): "Scott County",
    ("17", "161"): "Rock Island County",
    ("17", "073"): "Henry County",
    ("17", "131"): "Mercer County",
}


# ── Fiscal year helpers ───────────────────────────────────────────────────────

def _current_fy() -> int:
    """US federal fiscal year for today (Oct 1 starts a new FY)."""
    today = date.today()
    return today.year + 1 if today.month >= 10 else today.year


def _fy_date_range(num_years: int = 3) -> tuple[str, str, str, str]:
    """
    Returns (start_date, end_date, fy_start_label, fy_end_label) covering
    the last `num_years` fiscal years, inclusive of the current FY.
    """
    end_fy   = _current_fy()
    start_fy = end_fy - num_years + 1
    start_date = f"{start_fy - 1}-10-01"   # Oct 1 of year before start_fy
    end_date   = f"{end_fy}-09-30"          # Sep 30 of end_fy
    return start_date, end_date, f"FY{start_fy}", f"FY{end_fy}"


def _start_date_to_fy(date_str: Optional[str]) -> Optional[int]:
    """Convert an ISO date string to the US fiscal year it falls in."""
    if not date_str:
        return None
    try:
        parts = date_str[:10].split("-")
        year, month = int(parts[0]), int(parts[1])
        return year + 1 if month >= 10 else year
    except (ValueError, IndexError):
        return None


# ── API helpers ───────────────────────────────────────────────────────────────

def _post(path: str, body: dict) -> dict:
    resp = httpx.post(f"{BASE_URL}{path}", json=body, timeout=12.0)
    resp.raise_for_status()
    return resp.json()


def _filters(state_abbr: str, county_fips: str, start: str, end: str) -> dict:
    return {
        "award_type_codes": AWARD_TYPES,
        "place_of_performance_locations": [
            {"country": "USA", "state": state_abbr, "county": county_fips}
        ],
        "time_period": [{"start_date": start, "end_date": end}],
    }


# ── Core fetchers ─────────────────────────────────────────────────────────────

def _fetch_agency_breakdown(filters: dict) -> tuple[float, list[dict]]:
    """
    Returns (total_awarded, [{"agency": ..., "amount": ...}]) sorted by amount desc.
    Paginates if needed (usually all agencies fit in one page of 50).
    """
    agencies: list[dict] = []
    page = 1
    while True:
        data = _post("/search/spending_by_category/awarding_agency/", {
            "filters": filters,
            "limit": 50,
            "page": page,
        })
        results = data.get("results") or []
        for r in results:
            amt = r.get("amount") or 0
            agencies.append({"agency": r.get("name", "Unknown Agency"), "amount": amt})
        if not (data.get("page_metadata") or {}).get("hasNext"):
            break
        page += 1
        if page > 5:   # safety cap
            break

    agencies.sort(key=lambda x: x["amount"], reverse=True)
    total = sum(a["amount"] for a in agencies)
    return total, agencies


def _fetch_top_awards(filters: dict, limit: int = 5) -> list[dict]:
    """Returns the top `limit` awards by amount."""
    data = _post("/search/spending_by_award/", {
        "filters": filters,
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "CFDA Number", "CFDA Title",
            "Start Date", "Description",
        ],
        "page": 1,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
    })

    awards = []
    for r in data.get("results") or []:
        raw_id = r.get("generated_internal_id") or ""
        awards.append({
            "recipient":    _title_case(r.get("Recipient Name") or ""),
            "amount":       r.get("Award Amount") or 0,
            "agency":       r.get("Awarding Agency") or "",
            "cfda":         r.get("CFDA Number") or "",
            "description":  _truncate(r.get("Description") or "", 120),
            "fiscal_year":  _start_date_to_fy(r.get("Start Date")),
            "url":          f"https://www.usaspending.gov/award/{raw_id}/" if raw_id else None,
        })
    return awards


# ── String helpers ────────────────────────────────────────────────────────────

def _title_case(s: str) -> str:
    """Title-case an ALL-CAPS string."""
    return s.title() if s.isupper() else s


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len].rstrip() + "…" if len(s) > max_len else s


# ── Public interface ──────────────────────────────────────────────────────────

def fetch_funding_history(geoid: str) -> Optional[dict]:
    """
    Fetch federal grant funding history for the county containing the given
    census tract GEOID.

    Returns a dict with:
        county_label     — human-readable county name + state (e.g. "Scott County, IA")
        county_fips      — 3-digit county FIPS
        state_fips       — 2-digit state FIPS
        fy_range         — label like "FY2024–FY2026"
        total_awarded    — total dollars awarded (float)
        agency_breakdown — list of {agency, amount} sorted by amount desc
        top_awards       — list of top 5 {recipient, amount, agency, cfda,
                           description, fiscal_year, url}

    Returns None if the state FIPS is unrecognised or the API call fails.
    """
    if len(geoid) < 5:
        return None

    state_fips  = geoid[:2]
    county_fips = geoid[2:5]
    state_abbr  = _STATE_ABBR.get(state_fips)
    if not state_abbr:
        logger.warning("Unknown state FIPS %s for GEOID %s", state_fips, geoid)
        return None

    cache_key = (state_fips, county_fips)
    if cache_key in _cache:
        ts, val = _cache[cache_key]
        if time.monotonic() - ts < CACHE_TTL:
            return val

    county_name = _COUNTY_NAMES.get(
        (state_fips, county_fips),
        f"County {county_fips}",
    )
    county_label = f"{county_name}, {state_abbr}"

    start_date, end_date, fy_start, fy_end = _fy_date_range(num_years=3)
    fy_range = f"{fy_start}–{fy_end}"

    filters = _filters(state_abbr, county_fips, start_date, end_date)

    try:
        total, agency_breakdown = _fetch_agency_breakdown(filters)
        top_awards = _fetch_top_awards(filters, limit=5)
    except Exception as exc:
        logger.warning("USASpending API error for GEOID %s: %s", geoid, exc)
        _cache[cache_key] = (time.monotonic(), None)
        return None

    result = {
        "county_label":      county_label,
        "county_fips":       county_fips,
        "state_fips":        state_fips,
        "fy_range":          fy_range,
        "total_awarded":     round(total, 2),
        "agency_breakdown":  agency_breakdown,
        "top_awards":        top_awards,
    }

    _cache[cache_key] = (time.monotonic(), result)
    return result
