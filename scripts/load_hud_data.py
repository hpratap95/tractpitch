"""
Load HUD data files into TractPitch's hud schema.

  - hud.qct_designations  ← data/qct_data_2026.xlsx
  - hud.cdbg_eligibility  ← data/Community_Development_Block_Grant__CDBG__...csv

Run from the repo root:
    python3 scripts/load_hud_data.py

Requires: pandas, openpyxl, psycopg2-binary
The script connects to the TractPitch DB on localhost:5433.
"""

import os
import sys
import psycopg2
import pandas as pd
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://tractpitch:tractpitch_dev@localhost:5433/tractpitch",
)

DATA_DIR = Path(__file__).parent.parent / "data"

QCT_FILE  = DATA_DIR / "qct_data_2026.xlsx"
CDBG_FILE = DATA_DIR / "Community_Development_Block_Grant__CDBG__Eligibility_by_Census_Tract_-_CSV.csv"
OZ_FILE   = DATA_DIR / "OZ-2.0-Tract-Eligibility-2020-2024-ACS-Data.xlsx"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DB_URL)


# ── QCT loader ────────────────────────────────────────────────────────────────

def load_qct(conn):
    """
    Load HUD Qualified Census Tract designations from the Excel file.

    The source file has one row per census tract. The `qct` column is 1 when
    the tract is designated a QCT, 0 otherwise.

    GEOID is derived by zero-padding `tract_id` to 11 characters.
    """
    print(f"Reading {QCT_FILE.name}…")
    df = pd.read_excel(QCT_FILE, dtype={"state": int, "county": int, "tract_id": object})

    # tract_id is already the concatenated GEOID integer; zero-pad to 11
    df["geoid"] = df["tract_id"].astype(str).str.zfill(11)

    # Validate: every geoid should be 11 chars
    bad = df[df["geoid"].str.len() != 11]
    if len(bad):
        print(f"  WARNING: {len(bad)} rows with unexpected GEOID length — skipping")
        df = df[df["geoid"].str.len() == 11]

    df["is_qct"]      = df["qct"].astype(int) == 1
    df["state_fips"]  = df["state"].astype(str).str.zfill(2)
    df["county_fips"] = df["county"].astype(str).str.zfill(3)
    df["cbsa"]        = pd.to_numeric(df["cbsa"], errors="coerce").where(df["cbsa"].notna())

    rows = df[["geoid", "is_qct", "state_fips", "county_fips", "cbsa"]].values.tolist()

    print(f"  Loaded {len(rows):,} rows from file. Inserting into hud.qct_designations…")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE hud.qct_designations")
        cur.executemany(
            """
            INSERT INTO hud.qct_designations (geoid, is_qct, state_fips, county_fips, cbsa)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (geoid) DO UPDATE
              SET is_qct      = EXCLUDED.is_qct,
                  state_fips  = EXCLUDED.state_fips,
                  county_fips = EXCLUDED.county_fips,
                  cbsa        = EXCLUDED.cbsa,
                  loaded_at   = NOW()
            """,
            [
                (r[0], bool(r[1]), r[2], r[3], None if pd.isna(r[4]) else int(r[4]))
                for r in rows
            ],
        )

    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM hud.qct_designations")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM hud.qct_designations WHERE is_qct = TRUE")
        qct_count = cur.fetchone()[0]

    print(f"  hud.qct_designations: {total:,} tracts total, {qct_count:,} designated QCT")


# ── CDBG loader ───────────────────────────────────────────────────────────────

# HUD LMI threshold for CDBG eligibility: tract qualifies if ≥51% of residents
# are low-to-moderate income (standard HUD CDBG area-benefit threshold).
CDBG_LMI_THRESHOLD = 51.0


def load_cdbg(conn):
    """
    Load HUD Low-to-Moderate Income (LMI) Population by Tract data.

    Source columns:
        GEOID        – 11-digit census tract GEOID (stored as integer; zero-pad to 11)
        LOWMOD       – count of LMI persons in the tract
        LOWMODUNIV   – total population universe used for the percentage
        LOWMODPCT    – LMI percentage (LOWMOD / LOWMODUNIV * 100)

    A tract is marked 'CD Eligible' when LOWMODPCT >= 51 (HUD CDBG threshold).
    """
    print(f"Reading {CDBG_FILE.name}…")
    df = pd.read_csv(CDBG_FILE)

    # GEOID is stored as an integer (leading zeros dropped for low state FIPS)
    df["geoid"] = df["GEOID"].astype(str).str.zfill(11)

    # Derive eligibility from the LMI percentage
    df["eligibility"] = df["LOWMODPCT"].apply(
        lambda pct: "CD Eligible" if pd.notna(pct) and pct >= CDBG_LMI_THRESHOLD else "Ineligible"
    )

    rows = df[["geoid", "eligibility", "LOWMODPCT", "LOWMOD", "LOWMODUNIV"]].values.tolist()

    print(f"  Loaded {len(rows):,} rows. Inserting into hud.cdbg_eligibility…")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE hud.cdbg_eligibility")
        cur.executemany(
            """
            INSERT INTO hud.cdbg_eligibility
                (geoid, eligibility, lmod_pct, low_mod_population, total_population)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (geoid) DO UPDATE
              SET eligibility        = EXCLUDED.eligibility,
                  lmod_pct           = EXCLUDED.lmod_pct,
                  low_mod_population = EXCLUDED.low_mod_population,
                  total_population   = EXCLUDED.total_population,
                  loaded_at          = NOW()
            """,
            [
                (
                    r[0],
                    r[1],
                    None if pd.isna(r[2]) else float(r[2]),
                    None if pd.isna(r[3]) else int(r[3]),
                    None if pd.isna(r[4]) else int(r[4]),
                )
                for r in rows
            ],
        )

    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM hud.cdbg_eligibility")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM hud.cdbg_eligibility WHERE eligibility = 'CD Eligible'")
        elig_count = cur.fetchone()[0]

    print(f"  hud.cdbg_eligibility: {total:,} tracts total, {elig_count:,} CDBG eligible (LOWMODPCT ≥ {CDBG_LMI_THRESHOLD:.0f}%)")


# ── OZ 2.0 loader ─────────────────────────────────────────────────────────────

def load_oz(conn):
    """
    Load OZ 2.0 eligible census tracts from the opportunityzones.com Excel file.

    Source sheet: 'Tract Eligibility'
    Key columns:
        Census Tract     – 10-digit integer GEOID (zero-pad to 11)
        OZ 2.0 Eligible?.1 – 0 = not eligible, 1 = MFI-only, 2 = both tests
    """
    print(f"Reading {OZ_FILE.name} (sheet: 'Tract Eligibility')…")
    df = pd.read_excel(OZ_FILE, sheet_name="Tract Eligibility",
                       dtype={"Census Tract": object})

    df["geoid"]       = df["Census Tract"].astype(str).str.zfill(11)
    df["oz2_score"]   = pd.to_numeric(df["OZ 2.0 Eligible?.1"], errors="coerce").fillna(0).astype(int)
    df["oz2_eligible"] = df["oz2_score"] > 0

    # Validate GEOID length
    bad = df[df["geoid"].str.len() != 11]
    if len(bad):
        print(f"  WARNING: {len(bad)} rows with unexpected GEOID length — skipping")
        df = df[df["geoid"].str.len() == 11]

    rows = df[["geoid", "oz2_eligible", "oz2_score"]].values.tolist()
    print(f"  Loaded {len(rows):,} rows. Inserting into hud.opportunity_zones…")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE hud.opportunity_zones")
        cur.executemany(
            """
            INSERT INTO hud.opportunity_zones (geoid, oz2_eligible, oz2_score)
            VALUES (%s, %s, %s)
            ON CONFLICT (geoid) DO UPDATE
              SET oz2_eligible = EXCLUDED.oz2_eligible,
                  oz2_score    = EXCLUDED.oz2_score,
                  loaded_at    = NOW()
            """,
            [(str(r[0]), bool(r[1]), int(r[2])) for r in rows],
        )

    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM hud.opportunity_zones")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM hud.opportunity_zones WHERE oz2_eligible = TRUE")
        elig_count = cur.fetchone()[0]

    print(f"  hud.opportunity_zones: {total:,} tracts total, {elig_count:,} OZ 2.0 eligible")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to TractPitch DB…")
    try:
        conn = get_conn()
    except Exception as e:
        print(f"ERROR: Could not connect — {e}")
        sys.exit(1)

    try:
        load_qct(conn)
        print()
        load_cdbg(conn)
        print()
        load_oz(conn)
    finally:
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
