# TractPitch
**Grant Eligibility Screener — Project Doc**
*Last updated: June 23, 2026*

---

## What it is

TractPitch is a grant eligibility screener for community development professionals. You enter a street address, and TractPitch identifies which federal and state grant programs that census tract qualifies for — based on real ACS demographic data. Results can be downloaded as a formatted PDF report.

It is a standalone tool, separate from Locivus.

---

## Target Markets

- **Minneapolis–St. Paul metro** (Hennepin, Ramsey, Dakota, Anoka, Washington, Scott, Carver counties — Minnesota)
- **Quad Cities metro** (Scott County, Iowa + Rock Island, Henry, Mercer counties, Illinois)

These are the two active markets. Expanding to additional metros requires running the Census ACS and TIGER tract ETL pipelines for the new counties.

---

## How it works

1. User enters a street address on the landing page or screener (street, city, state, ZIP)
2. TractPitch geocodes the address via the Census Bureau geocoder with Nominatim/OSM as fallback
3. The coordinates are matched to a census tract using PostGIS point-in-polygon lookup
4. That tract's 2022 ACS demographic profile is pulled (income, poverty rate, minority %, renter %, unemployment, education)
5. Demographics are screened against 20+ federal and state grant programs using eligibility thresholds
6. HUD designation flags are checked (QCT 2026, CDBG LMI eligibility, OZ 2.0 eligibility)
7. Matched grants are enriched with live Grants.gov solicitation data (open deadlines, forecasted, formula)
8. Federal funding history for the county is fetched from USASpending.gov (FY2022–FY2026)
9. User can download a PDF report with the full tract profile and grant list

---

## Pages

| URL | Description |
|---|---|
| `/` | Landing page — hero search, features, pricing |
| `/screener` | Grant screener app |
| `/subscribe/success` | Stripe checkout success page |
| `/subscribe/cancel` | Stripe checkout cancel page |

---

## Running it locally

**Prerequisites:** Docker Desktop running.

**Start TractPitch:**
```bash
cd projects/tractpitch
docker compose up --build
```

**Open:** [http://localhost:8001](http://localhost:8001)

TractPitch runs its own PostGIS database (`tractpitch` on port 5433), separate from Locivus.

**Required environment variables (`.env`):**
```
DATABASE_URL=...
LOG_LEVEL=INFO
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
```

---

## Grant Database

20+ programs are seeded in `grants.federal_grants` — 17 federal, 3 Minnesota state.

Eligibility is determined by matching tract demographics against threshold columns on each grant:

| Column | Meaning |
|---|---|
| `min_poverty_rate` | Tract poverty rate must be at or above this |
| `max_median_hh_income` | Tract median income must be at or below this |
| `min_pct_minority` | Combined Black + Hispanic + Asian population % |
| `min_pct_renter` | Share of renter-occupied housing units |
| `min_unemployment` | Unemployment rate (100 minus employment rate) |
| `min_population` | Minimum tract population |
| `max_pct_bachelors` | Bachelor's degree attainment must be at or below this |
| `state_fips` | When set, grant only appears for tracts in that state |

A `NULL` threshold means that criterion is not applied for that grant.

To add a new grant, insert a row into `grants.federal_grants` and add the same row to `migrations/001_schema.sql` so it persists on fresh deployments.

---

## HUD Data

Three HUD designation flags are checked per tract and shown as badges in the UI:

| Table | Source | Description |
|---|---|---|
| `hud.qct_designations` | HUD QCT 2026 Excel | Qualified Census Tract status |
| `hud.cdbg_eligibility` | HUD LMI national CSV | CDBG Low-to-Moderate Income eligible (≥51% LMI) |
| `hud.opportunity_zones` | opportunityzones.com ACS analysis | OZ 2.0 eligibility score (not official Treasury list) |

Load/refresh via `scripts/load_hud_data.py`.

---

## External Integrations

| Service | Purpose | Auth |
|---|---|---|
| Census Bureau Geocoder | Primary geocoder | None (free) |
| Nominatim / OpenStreetMap | Fallback geocoder | None (free, User-Agent required) |
| Grants.gov search2 API | Live solicitation data per grant | None (free) |
| USASpending.gov API | County-level federal award history | None (free) |
| Stripe | Pro subscription payments ($49/month) | `STRIPE_SECRET_KEY` |

**Geocoding fallback:** If the Census geocoder returns no match (address range gap), the request is automatically retried against Nominatim. The `geocode_source` field in the response indicates which was used.

**Grants.gov caching:** 1-hour in-memory cache per grant lookup. Formula grants (CDBG 14.218, HOME 14.239, Title I 84.010, WIOA 17.258) are short-circuited and never hit Grants.gov.

**USASpending caching:** 24-hour in-memory cache per county. Data is county-level only — census tract filtering is not available via the USASpending API.

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service + DB status |
| `GET` | `/api/v1/geocode?address=...` | Address → lat/lon (Census + Nominatim fallback) |
| `POST` | `/api/v1/grants/screen` | Screen grants for a lat/lon or GEOID |
| `POST` | `/api/v1/grants/screen` (format: pdf) | Same, returns downloadable PDF |
| `POST` | `/api/v1/waitlist` | Save email to Pro plan waitlist |
| `POST` | `/api/v1/subscribe` | Create Stripe Checkout Session, returns `checkout_url` |

---

## Stripe Subscriptions

TractPitch Pro is $49/month via Stripe Checkout with a 14-day free trial.

On startup, the API checks for a "TractPitch Pro" product and $49/month recurring price in Stripe. If they don't exist, they are created automatically. The price ID is cached in memory for the session.

The "Start Free Trial" button on the landing page calls `POST /api/v1/subscribe`, receives a Stripe-hosted checkout URL, and redirects the user. After checkout, Stripe redirects to `/subscribe/success` or `/subscribe/cancel`.

**Migrations:** No database tables needed — Stripe holds all subscription state.

---

## Database Schemas

| Schema | Tables | Purpose |
|---|---|---|
| `geo` | `census_tract` | TIGER/Line tract boundaries (PostGIS geometry) |
| `demo` | `tract_demographics` | ACS demographic profiles by tract + vintage |
| `grants` | `federal_grants` | Grant program eligibility rules |
| `hud` | `qct_designations`, `cdbg_eligibility`, `opportunity_zones` | HUD designation flags |
| `public` | `waitlist` | Pro plan email waitlist |

---

## Migrations

| File | Description |
|---|---|
| `migrations/001_schema.sql` | All schemas, tables, indexes, and seed data |
| `migrations/002_waitlist.sql` | `public.waitlist` table for Pro plan email capture |

---

## Adding a New Metro Area

1. Find the county FIPS codes for the target metro ([census.gov ANSI codes](https://www.census.gov/library/reference/code-lists/ansi.html))
2. Run the TIGER tract and Census ACS ETL pipelines for the new counties
3. Load the tract boundaries and demographics into TractPitch's DB (port 5433)
4. Add the new state to the state dropdown in `app/templates/index.html` and update the disclaimer banner
5. Add any state-specific grant programs to `grants.federal_grants` with the appropriate `state_fips`

---

## Roadmap

- Complete Stripe integration testing with real test keys
- Add Iowa and Illinois state-specific grant programs for the Quad Cities market
- Expand to additional metros (requires ETL run per new county set)
- User accounts — save searches, email alerts when deadlines open
- Narrative generation — auto-written grant narrative paragraphs from tract demographics
- Multi-tract comparison view
- Bulk address upload (CSV) for Pro plan
