"""
USASpending Historical Awards — Layer 4 of TractPitch grant enrichment.
Also provides per-program competitiveness data (Layer 5) via
fetch_program_competitiveness().

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

# Competitiveness cache: (cfda, state_fips) → (timestamp, result)
_comp_cache: dict[tuple[str, str], tuple[float, Optional[dict]]] = {}

# National-only competitiveness cache: cfda → (timestamp, nat_count, amounts)
# Keyed by CFDA alone — national data is state-independent, so one fetch
# serves all states and avoids redundant API calls.
_nat_cache: dict[str, tuple[float, int, list]] = {}

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

def _post(path: str, body: dict, timeout: float = 45.0) -> dict:
    resp = httpx.post(f"{BASE_URL}{path}", json=body, timeout=timeout)
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
    """
    Returns the top `limit` awards by amount, restricted to awards whose
    Start Date falls in FY2022 or later (Start Date >= 2021-10-01).

    The USASpending search API has no Start Date filter, so we fetch a larger
    batch and filter in-code. Awards with a null Start Date are excluded because
    we cannot verify when they originated.
    """
    data = _post("/search/spending_by_award/", {
        "filters": filters,
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "CFDA Number", "CFDA Title",
            "Start Date", "Description",
        ],
        "page": 1,
        "limit": 25,   # fetch extra to have enough after filtering
        "sort": "Award Amount",
        "order": "desc",
    })

    awards = []
    for r in data.get("results") or []:
        fy = _start_date_to_fy(r.get("Start Date"))
        if fy is None or fy < 2022:
            continue   # exclude pre-FY2022 and undated awards

        raw_id = r.get("generated_internal_id") or ""
        awards.append({
            "recipient":    _title_case(r.get("Recipient Name") or ""),
            "amount":       r.get("Award Amount") or 0,
            "agency":       r.get("Awarding Agency") or "",
            "cfda":         r.get("CFDA Number") or "",
            "description":  _truncate(r.get("Description") or "", 120),
            "fiscal_year":  fy,
            "url":          f"https://www.usaspending.gov/award/{raw_id}/" if raw_id else None,
        })
        if len(awards) == limit:
            break

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

    # Run both calls independently — if one times out, still return the other.
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    total, agency_breakdown, top_awards = 0.0, [], []

    def _get_agencies(): return _fetch_agency_breakdown(filters)
    def _get_awards():   return _fetch_top_awards(filters, limit=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_agencies = pool.submit(_get_agencies)
        f_awards   = pool.submit(_get_awards)

        try:
            total, agency_breakdown = f_agencies.result()
        except Exception as exc:
            logger.warning("USASpending agency breakdown failed for %s: %s", geoid, exc)

        try:
            top_awards = f_awards.result()
        except Exception as exc:
            logger.warning("USASpending top awards failed for %s: %s", geoid, exc)

    # Nothing came back at all — cache None to avoid hammering a down API
    if not agency_breakdown and not top_awards:
        logger.warning("USASpending returned no data for GEOID %s", geoid)
        _cache[cache_key] = (time.monotonic(), None)
        return None

    result = {
        "county_label":      county_label,
        "county_fips":       county_fips,
        "state_fips":        state_fips,
        "fy_range":          fy_range,
        "total_awarded":     round(total, 2) if total else None,
        "agency_breakdown":  agency_breakdown,
        "top_awards":        top_awards,
    }

    _cache[cache_key] = (time.monotonic(), result)
    return result


# ── Program competitiveness (Layer 5) ────────────────────────────────────────

# CFDA numbers treated as formula grants — no competitive awards to count.
# Kept in sync with grants_gov.py FORMULA_CFDAS.
_FORMULA_CFDAS: frozenset[str] = frozenset({
    "14.218",  # CDBG
    "14.239",  # HOME
    "84.010",  # Title I
    "17.258",  # WIOA Adult
})

_STATE_NAMES: dict[str, str] = {
    "01": "Alabama",      "02": "Alaska",       "04": "Arizona",
    "05": "Arkansas",     "06": "California",   "08": "Colorado",
    "09": "Connecticut",  "10": "Delaware",     "11": "D.C.",
    "12": "Florida",      "13": "Georgia",      "15": "Hawaii",
    "16": "Idaho",        "17": "Illinois",     "18": "Indiana",
    "19": "Iowa",         "20": "Kansas",       "21": "Kentucky",
    "22": "Louisiana",    "23": "Maine",        "24": "Maryland",
    "25": "Massachusetts","26": "Michigan",     "27": "Minnesota",
    "28": "Mississippi",  "29": "Missouri",     "30": "Montana",
    "31": "Nebraska",     "32": "Nevada",       "33": "New Hampshire",
    "34": "New Jersey",   "35": "New Mexico",   "36": "New York",
    "37": "North Carolina","38": "North Dakota","39": "Ohio",
    "40": "Oklahoma",     "41": "Oregon",       "42": "Pennsylvania",
    "44": "Rhode Island", "45": "South Carolina","46": "South Dakota",
    "47": "Tennessee",    "48": "Texas",        "49": "Utah",
    "50": "Vermont",      "51": "Virginia",     "53": "Washington",
    "54": "West Virginia","55": "Wisconsin",    "56": "Wyoming",
}


def _award_count(filters: dict) -> int:
    """
    Call /search/spending_by_award_count/ and return the grants sub-count.
    Returns 0 on any error.
    """
    try:
        data = _post("/search/spending_by_award_count/", {"filters": filters})
        return int((data.get("results") or {}).get("grants", 0))
    except Exception as exc:
        logger.debug("award_count failed: %s", exc)
        return 0


def _top_amounts(filters: dict, limit: int = 50) -> list[float]:
    """
    Fetch top `limit` award amounts (sorted desc) for a filter set.
    Returns empty list on any error.
    """
    try:
        data = _post("/search/spending_by_award/", {
            "filters": filters,
            "fields":  ["Award Amount"],
            "limit":   limit,
            "page":    1,
            "sort":    "Award Amount",
            "order":   "desc",
        })
        return [
            r["Award Amount"]
            for r in (data.get("results") or [])
            if (r.get("Award Amount") or 0) > 0
        ]
    except Exception as exc:
        logger.debug("top_amounts failed: %s", exc)
        return []


def fetch_program_competitiveness(cfda: str, state_fips: str) -> Optional[dict]:
    """
    Return competitive award statistics for a CFDA program.

    Makes three concurrent USASpending calls:
      A. spending_by_award_count  (national, most recent complete FY) → count
      B. spending_by_award top-50 (national, most recent complete FY) → max + avg
      C. spending_by_award_count  (state, last 3 complete FY)         → state count

    Returns None for formula grants, unknown states, or when the API
    returns no data (caller should suppress the UI block).

    Result keys:
        national_count  int   — awards nationally in fy_label
        national_max    float — largest single award in fy_label (or None)
        national_avg    float — avg award in fy_label; exact when national_count ≤ 50,
                                None when count > 50 and sample is insufficient
        state_count     int   — awards in this state over fy_range
        state_name      str   — e.g. "Iowa"
        fy_label        str   — e.g. "FY2025"
        fy_range        str   — e.g. "FY2023–FY2025"
    """
    if cfda in _FORMULA_CFDAS:
        return None

    state_abbr = _STATE_ABBR.get(state_fips)
    state_name = _STATE_NAMES.get(state_fips)
    if not state_abbr:
        return None

    cache_key = (cfda, state_fips)
    if cache_key in _comp_cache:
        ts, val = _comp_cache[cache_key]
        if time.monotonic() - ts < CACHE_TTL:
            return val

    # Most recent *complete* fiscal year (current FY - 1)
    recent_fy    = _current_fy() - 1
    recent_start = f"{recent_fy - 1}-10-01"
    recent_end   = f"{recent_fy}-09-30"
    fy_label     = f"FY{recent_fy}"

    # 3-year state window (last 3 complete FY)
    state_start_fy = recent_fy - 2
    state_start    = f"{state_start_fy - 1}-10-01"
    fy_range       = f"FY{state_start_fy}–FY{recent_fy}"

    nat_base_filters = {
        "award_type_codes": AWARD_TYPES,
        "program_numbers":  [cfda],
        "time_period":      [{"start_date": recent_start, "end_date": recent_end}],
    }
    state_filters = {
        "award_type_codes": AWARD_TYPES,
        "program_numbers":  [cfda],
        "time_period":      [{"start_date": state_start, "end_date": recent_end}],
        "place_of_performance_locations": [{"country": "USA", "state": state_abbr}],
    }

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # National data is state-independent — check the national cache first.
    # This lets Iowa and Minnesota share one USASpending call per CFDA.
    nat_cached = _nat_cache.get(cfda)
    if nat_cached and time.monotonic() - nat_cached[0] < CACHE_TTL:
        nat_count, amounts = nat_cached[1], nat_cached[2]
        # Only need the state count call
        state_count = _award_count(state_filters)
    else:
        results: dict = {}

        def _a(): return ("nat_count",   _award_count(nat_base_filters))
        def _b(): return ("amounts",     _top_amounts(nat_base_filters, limit=50))
        def _c(): return ("state_count", _award_count(state_filters))

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(f) for f in (_a, _b, _c)]
            for fut in as_completed(futures):
                try:
                    k, v = fut.result()
                    results[k] = v
                except Exception as exc:
                    logger.warning("Competitiveness call failed: %s", exc)

        nat_count   = results.get("nat_count", 0)
        amounts     = results.get("amounts", [])
        state_count = results.get("state_count", 0)

        # If nat_count timed out (0) but amounts succeeded, use len(amounts)
        # as a minimum count — we know there are at least that many awards.
        if nat_count == 0 and amounts:
            nat_count = len(amounts)

        # Cache national data by CFDA alone for reuse across states
        _nat_cache[cfda] = (time.monotonic(), nat_count, amounts)

    # No national data at all → don't surface anything
    if nat_count == 0 and not amounts:
        _comp_cache[cache_key] = (time.monotonic(), None)
        return None

    national_max = amounts[0] if amounts else None
    # Exact average only when we captured the full population (count ≤ sample size)
    national_avg = (sum(amounts) / nat_count) if (nat_count > 0 and nat_count <= len(amounts)) else None

    result = {
        "national_count": nat_count,
        "national_max":   national_max,
        "national_avg":   national_avg,
        "state_count":    state_count,
        "state_name":     state_name,
        "fy_label":       fy_label,
        "fy_range":       fy_range,
    }

    _comp_cache[cache_key] = (time.monotonic(), result)
    return result
