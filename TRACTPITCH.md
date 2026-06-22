# TractPitch
**Grant Eligibility Screener — Project Doc**
*Last updated: June 22, 2026*

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

1. User enters a street address (street, city, state, ZIP)
2. TractPitch geocodes the address via the Census Bureau geocoder (server-side proxy)
3. The coordinates are matched to a census tract using PostGIS point-in-polygon lookup
4. That tract's 2022 ACS demographic profile is pulled (income, poverty rate, minority %, renter %, unemployment, education)
5. Demographics are screened against 20 federal and state grant programs using eligibility thresholds
6. Matched grants are returned with specific qualifying reasons per grant
7. User can download a PDF report with the full tract profile and grant list

---

## Running it locally

**Prerequisites:** Docker Desktop running, Locivus DB running (`docker compose up` in the locivus folder).

**Start TractPitch:**
```bash
cd projects/tractpitch
docker compose up --build
```

**Open:** [http://localhost:8001](http://localhost:8001)

TractPitch runs its own PostGIS database (`tractpitch` on port 5433), separate from Locivus.

---

## Grant Database

20 programs are seeded in `grants.federal_grants` — 17 federal, 3 Minnesota state.

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

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service + DB status |
| `GET` | `/api/v1/geocode?address=...` | Address → lat/lon (Census geocoder proxy) |
| `POST` | `/api/v1/grants/screen` | Screen grants for a lat/lon or GEOID |
| `POST` | `/api/v1/grants/screen` (format: pdf) | Same, returns downloadable PDF |

---

## Adding a New Metro Area

TractPitch's database is fully independent of Locivus. To add a new metro:

1. Find the county FIPS codes for the target metro (use [census.gov](https://www.census.gov/library/reference/code-lists/ansi.html))
2. Add the state + county FIPS to `quad_cities_counties` (or a new config field) in the Locivus `app/core/config.py`
3. Add new ETL endpoints in Locivus `app/api/routes/etl.py` following the Quad Cities pattern
4. Trigger the two pipelines via the Locivus API:
   - `POST /api/v1/etl/run/tiger_tracts/{metro}`
   - `POST /api/v1/etl/run/census_acs/{metro}`
5. Export the new tracts from the Locivus DB and load them into TractPitch's DB (port 5433)
6. Add any state-specific grant programs for the new market to `grants.federal_grants` with the appropriate `state_fips`

---

## Roadmap

- Add Iowa and Illinois state-specific grant programs for the Quad Cities market
- Expand to additional metros (requires ETL run per new county set)
- Narrative generation — auto-written grant narrative paragraphs from tract demographics
- Multi-tract comparison view
- Saved searches / export history
