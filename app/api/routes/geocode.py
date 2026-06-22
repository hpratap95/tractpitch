import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/geocode")
def geocode_address(address: str = Query(..., description="Full street address")):
    """
    Convert a street address to latitude/longitude using the Census Bureau geocoder.
    Proxied server-side to avoid browser CORS restrictions.
    """
    url = (
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        f"?address={httpx.URL('', params={'address': address}).params['address']}"
        "&benchmark=Public_AR_Current&format=json"
    )
    # Build the URL properly
    params = {
        "address":   address,
        "benchmark": "Public_AR_Current",
        "format":    "json",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Geocoder timed out. Try again.")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Geocoder error: {e}")

    matches = (data.get("result") or {}).get("addressMatches") or []
    if not matches:
        raise HTTPException(
            status_code=404,
            detail="Address not found. Try adding more detail, like city and state.",
        )

    coords = matches[0]["coordinates"]
    return {
        "latitude":  coords["y"],
        "longitude": coords["x"],
        "matched_address": matches[0].get("matchedAddress"),
    }
