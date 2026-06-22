import logging

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)

CENSUS_URL    = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA  = "TractPitch/1.0 (grant eligibility screener)"


def _geocode_census(address: str, client: httpx.Client) -> dict | None:
    """Try the Census Bureau geocoder. Returns {latitude, longitude, matched_address} or None."""
    try:
        resp = client.get(CENSUS_URL, params={
            "address":   address,
            "benchmark": "Public_AR_Current",
            "format":    "json",
        })
        resp.raise_for_status()
        matches = (resp.json().get("result") or {}).get("addressMatches") or []
        if not matches:
            return None
        coords = matches[0]["coordinates"]
        return {
            "latitude":        coords["y"],
            "longitude":       coords["x"],
            "matched_address": matches[0].get("matchedAddress"),
            "geocode_source":  "census",
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Geocoder timed out. Try again.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Geocoder error: {e}")


def _geocode_nominatim(address: str, client: httpx.Client) -> dict | None:
    """
    Fallback to Nominatim (OpenStreetMap). Returns {latitude, longitude, matched_address} or None.
    Used when the Census geocoder has an address range gap.
    """
    try:
        resp = client.get(NOMINATIM_URL, params={
            "q":              address,
            "format":         "json",
            "limit":          1,
            "addressdetails": 1,
            "countrycodes":   "us",
        }, headers={"User-Agent": NOMINATIM_UA})
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        r = results[0]
        return {
            "latitude":        float(r["lat"]),
            "longitude":       float(r["lon"]),
            "matched_address": r.get("display_name", address),
            "geocode_source":  "nominatim",
        }
    except Exception as exc:
        logger.warning("Nominatim fallback failed: %s", exc)
        return None


@router.get("/geocode")
def geocode_address(address: str = Query(..., description="Full street address")):
    """
    Convert a street address to latitude/longitude.

    Primary: Census Bureau geocoder (most accurate for US addresses).
    Fallback: Nominatim/OpenStreetMap (catches Census address range gaps).
    Proxied server-side to avoid browser CORS restrictions.
    """
    with httpx.Client(timeout=15.0) as client:
        result = _geocode_census(address, client)

        if result is None:
            logger.info("Census geocoder returned no match for '%s' — trying Nominatim", address)
            result = _geocode_nominatim(address, client)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Address not found. Check the street address, city, and state and try again.",
        )

    return result
