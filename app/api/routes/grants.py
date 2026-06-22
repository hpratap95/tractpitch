import io
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()


class GrantScreenRequest(BaseModel):
    geoid: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    vintage: int = 2022
    format: Literal["json", "pdf"] = "json"

    @model_validator(mode="after")
    def require_lookup_key(self):
        has_geoid = bool(self.geoid)
        has_latlng = self.latitude is not None and self.longitude is not None
        if not has_geoid and not has_latlng:
            raise ValueError("Provide either 'geoid' or both 'latitude' and 'longitude'.")
        return self


def _resolve_geoid(db: Session, req: GrantScreenRequest) -> str:
    if req.geoid:
        return req.geoid

    row = db.execute(text("""
        SELECT geoid
        FROM geo.census_tract
        WHERE ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
        LIMIT 1
    """), {"lat": req.latitude, "lng": req.longitude}).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=(
                "No census tract found at the given coordinates. "
                "Ensure TIGER tract boundaries have been loaded via POST /api/v1/etl/run/tiger_tracts."
            ),
        )
    return row["geoid"]


def _fetch_demographics(db: Session, geoid: str, vintage: int) -> dict:
    row = db.execute(text("""
        SELECT
            d.geoid,
            d.total_population,
            d.median_hh_income,
            d.poverty_rate,
            d.pct_renter_occupied,
            d.pct_bachelors_plus,
            d.employment_rate,
            d.pct_black_alone,
            d.pct_hispanic,
            d.pct_asian_alone,
            ct.name AS tract_name,
            ct.state_fips
        FROM demo.tract_demographics d
        JOIN geo.census_tract ct ON ct.geoid = d.geoid
        WHERE d.geoid = :geoid AND d.acs_vintage = :vintage
    """), {"geoid": geoid, "vintage": vintage}).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No {vintage} ACS demographics found for tract {geoid}.",
        )
    return dict(row)


def _screen_grants(db: Session, demo: dict) -> list[dict]:
    pct_minority = sum(filter(None, [
        demo.get("pct_black_alone") or 0,
        demo.get("pct_hispanic") or 0,
        demo.get("pct_asian_alone") or 0,
    ]))
    unemployment = (
        100 - demo["employment_rate"]
        if demo.get("employment_rate") is not None
        else None
    )

    params = {
        "poverty_rate":       demo.get("poverty_rate") or 0,
        "median_hh_income":   demo.get("median_hh_income") or 999999,
        "pct_minority":       pct_minority,
        "pct_renter":         demo.get("pct_renter_occupied") or 0,
        "unemployment":       unemployment if unemployment is not None else 0,
        "population":         demo.get("total_population") or 0,
        "pct_bachelors":      demo.get("pct_bachelors_plus") or 100,
    }

    params["tract_state_fips"] = demo.get("state_fips")

    rows = db.execute(text("""
        SELECT
            id::text,
            program_name,
            agency,
            program_number,
            grant_type,
            description,
            max_award_amount,
            funding_url,
            min_poverty_rate,
            max_median_hh_income,
            min_pct_minority,
            min_pct_renter,
            min_unemployment,
            min_population,
            max_pct_bachelors
        FROM grants.federal_grants
        WHERE is_active = TRUE
          AND (state_fips IS NULL OR state_fips = :tract_state_fips)
          AND (min_poverty_rate      IS NULL OR :poverty_rate     >= min_poverty_rate)
          AND (max_median_hh_income  IS NULL OR :median_hh_income <= max_median_hh_income)
          AND (min_pct_minority      IS NULL OR :pct_minority     >= min_pct_minority)
          AND (min_pct_renter        IS NULL OR :pct_renter       >= min_pct_renter)
          AND (min_unemployment      IS NULL OR :unemployment     >= min_unemployment)
          AND (min_population        IS NULL OR :population       >= min_population)
          AND (max_pct_bachelors     IS NULL OR :pct_bachelors    <= max_pct_bachelors)
        ORDER BY program_name
    """), params).mappings().all()

    results = []
    for row in rows:
        g = dict(row)
        g["matched_criteria"] = _build_match_reasons(g, demo, pct_minority, unemployment)
        # Strip threshold columns from the response payload
        for col in (
            "min_poverty_rate", "max_median_hh_income", "min_pct_minority",
            "min_pct_renter", "min_unemployment", "min_population", "max_pct_bachelors",
        ):
            g.pop(col, None)
        results.append(g)

    return results


def _build_match_reasons(grant: dict, demo: dict, pct_minority: float, unemployment: Optional[float]) -> list[str]:
    reasons = []

    if grant["min_poverty_rate"] is not None and demo.get("poverty_rate") is not None:
        reasons.append(
            f"Poverty rate {demo['poverty_rate']:.1f}% meets ≥{grant['min_poverty_rate']:.0f}% threshold"
        )
    if grant["max_median_hh_income"] is not None and demo.get("median_hh_income") is not None:
        reasons.append(
            f"Median HH income ${demo['median_hh_income']:,} meets ≤${grant['max_median_hh_income']:,} threshold"
        )
    if grant["min_pct_minority"] is not None:
        reasons.append(
            f"Minority population {pct_minority:.1f}% meets ≥{grant['min_pct_minority']:.0f}% threshold"
        )
    if grant["min_pct_renter"] is not None and demo.get("pct_renter_occupied") is not None:
        reasons.append(
            f"Renter-occupied {demo['pct_renter_occupied']:.1f}% meets ≥{grant['min_pct_renter']:.0f}% threshold"
        )
    if grant["min_unemployment"] is not None and unemployment is not None:
        reasons.append(
            f"Unemployment rate {unemployment:.1f}% meets ≥{grant['min_unemployment']:.0f}% threshold"
        )
    if grant["min_population"] is not None and demo.get("total_population") is not None:
        reasons.append(
            f"Population {demo['total_population']:,} meets ≥{grant['min_population']:,} threshold"
        )
    if grant["max_pct_bachelors"] is not None and demo.get("pct_bachelors_plus") is not None:
        reasons.append(
            f"Bachelor's degree rate {demo['pct_bachelors_plus']:.1f}% meets ≤{grant['max_pct_bachelors']:.0f}% threshold"
        )

    return reasons


@router.post("/screen")
def screen_grants(payload: GrantScreenRequest, db: Session = Depends(get_db)):
    """
    Return federal and state grants for which a census tract qualifies.

    Supply either a tract `geoid` or `latitude`/`longitude` coordinates.
    Eligibility is evaluated against the tract's ACS demographic data.
    Pass `"format": "pdf"` to receive a downloadable PDF report instead of JSON.
    """
    geoid = _resolve_geoid(db, payload)
    demo = _fetch_demographics(db, geoid, payload.vintage)
    matched = _screen_grants(db, demo)

    tract_profile = {
        "total_population":  demo.get("total_population"),
        "median_hh_income":  demo.get("median_hh_income"),
        "poverty_rate":      demo.get("poverty_rate"),
        "pct_renter":        demo.get("pct_renter_occupied"),
        "pct_bachelors":     demo.get("pct_bachelors_plus"),
        "pct_minority":      round(
            (demo.get("pct_black_alone") or 0)
            + (demo.get("pct_hispanic") or 0)
            + (demo.get("pct_asian_alone") or 0),
            1,
        ),
        "unemployment_rate": round(100 - demo["employment_rate"], 1)
        if demo.get("employment_rate") is not None
        else None,
    }

    if payload.format == "pdf":
        from app.reports.grants_pdf import build_grants_pdf
        pdf_bytes = build_grants_pdf(
            geoid=geoid,
            tract_name=demo.get("tract_name"),
            vintage=payload.vintage,
            profile=tract_profile,
            grants=matched,
        )
        filename = f"grants_{geoid}_{payload.vintage}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return {
        "geoid": geoid,
        "tract_name": demo.get("tract_name"),
        "acs_vintage": payload.vintage,
        "tract_profile": tract_profile,
        "grants_matched": len(matched),
        "grants": matched,
    }
