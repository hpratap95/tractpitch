-- TractPitch schema
-- Run once on a fresh database: psql -U tractpitch tractpitch < migrations/001_schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Schemas ───────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS geo;
CREATE SCHEMA IF NOT EXISTS demo;
CREATE SCHEMA IF NOT EXISTS grants;

-- ── geo.census_tract ──────────────────────────────────────────────────────────
-- Loaded by the TIGER/Line ETL. Used for lat/lng → GEOID point-in-polygon lookup.

CREATE TABLE IF NOT EXISTS geo.census_tract (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    geoid        VARCHAR(11) NOT NULL UNIQUE,
    state_fips   CHAR(2)     NOT NULL,
    county_fips  CHAR(3)     NOT NULL,
    tract_code   CHAR(6)     NOT NULL,
    name         VARCHAR(100),
    land_area_sqm  BIGINT,
    water_area_sqm BIGINT,
    geometry     GEOMETRY(MultiPolygon, 4326) NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_census_tract_geom  ON geo.census_tract USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_census_tract_geoid ON geo.census_tract(geoid);

-- ── demo.tract_demographics ───────────────────────────────────────────────────
-- Loaded by the Census ACS ETL. Contains the demographic variables used for
-- grant eligibility screening.

CREATE TABLE IF NOT EXISTS demo.tract_demographics (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    geoid               VARCHAR(11) NOT NULL,
    acs_vintage         SMALLINT    NOT NULL,
    total_population    INTEGER,
    median_hh_income    INTEGER,
    poverty_rate        NUMERIC(5,2),
    employment_rate     NUMERIC(5,2),
    pct_bachelors_plus  NUMERIC(5,2),
    pct_renter_occupied NUMERIC(5,2),
    pct_black_alone     NUMERIC(5,2),
    pct_hispanic        NUMERIC(5,2),
    pct_asian_alone     NUMERIC(5,2),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (geoid, acs_vintage)
);

CREATE INDEX IF NOT EXISTS idx_tract_demo_geoid ON demo.tract_demographics(geoid);

-- ── grants.federal_grants ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS grants.federal_grants (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    program_name          VARCHAR(255) NOT NULL,
    agency                VARCHAR(255) NOT NULL,
    program_number        VARCHAR(50),
    grant_type            VARCHAR(10)  NOT NULL CHECK (grant_type IN ('federal', 'state')),
    description           TEXT,
    max_award_amount      BIGINT,
    funding_url           TEXT,
    min_poverty_rate      NUMERIC(5,2),
    max_median_hh_income  INTEGER,
    min_pct_minority      NUMERIC(5,2),
    min_pct_renter        NUMERIC(5,2),
    min_unemployment      NUMERIC(5,2),
    min_population        INTEGER,
    max_pct_bachelors     NUMERIC(5,2),
    is_active             BOOLEAN DEFAULT TRUE,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_federal_grants_type ON grants.federal_grants(grant_type);

-- ── Seed: 20 federal and state grant programs ─────────────────────────────────

INSERT INTO grants.federal_grants (
    program_name, agency, program_number, grant_type, description,
    max_award_amount, funding_url,
    min_poverty_rate, max_median_hh_income, min_pct_minority,
    min_pct_renter, min_unemployment, min_population, max_pct_bachelors
) VALUES

('Community Development Block Grant (CDBG)', 'HUD', '14.218', 'federal',
 'Flexible funding for housing, economic development, and public improvements in low-to-moderate income communities.',
 5000000, 'https://www.hud.gov/program_offices/comm_planning/cdbg',
 NULL, 75000, NULL, NULL, NULL, NULL, NULL),

('HOME Investment Partnerships Program', 'HUD', '14.239', 'federal',
 'Expands supply of affordable rental housing and homeownership opportunities for low-income households.',
 3000000, 'https://www.hud.gov/program_offices/comm_planning/home',
 NULL, 75000, NULL, 30.0, NULL, NULL, NULL),

('CDFI Fund Financial Assistance', 'U.S. Treasury / CDFI Fund', '21.020', 'federal',
 'Grants to certified Community Development Financial Institutions serving economically distressed communities.',
 2000000, 'https://www.cdfifund.gov/programs-training/Programs/cdfi-program',
 20.0, NULL, NULL, NULL, NULL, NULL, NULL),

('New Markets Tax Credit Program', 'U.S. Treasury / CDFI Fund', '21.019', 'federal',
 'Tax credit allocation to attract private investment into low-income communities through qualified CDEs.',
 NULL, 'https://www.cdfifund.gov/programs-training/Programs/new-markets-tax-credit',
 20.0, NULL, NULL, NULL, NULL, NULL, NULL),

('EDA Economic Development Assistance Programs', 'U.S. Department of Commerce / EDA', '11.307', 'federal',
 'Public works and technical assistance grants to distressed communities to create jobs and leverage private investment.',
 3000000, 'https://www.eda.gov/funding/programs',
 15.0, 75000, NULL, NULL, NULL, NULL, NULL),

('Head Start Program', 'HHS / Administration for Children and Families', '93.600', 'federal',
 'Comprehensive early childhood education and family support services for low-income children ages 0–5.',
 NULL, 'https://eclkc.ohs.acf.hhs.gov/about-us/article/head-start-program-facts-fiscal-year-2022',
 20.0, NULL, NULL, NULL, NULL, NULL, NULL),

('HRSA Health Center Program', 'HHS / Health Resources and Services Administration', '93.224', 'federal',
 'Grants to establish and expand Federally Qualified Health Centers serving medically underserved populations.',
 650000, 'https://bphc.hrsa.gov/funding',
 20.0, NULL, NULL, NULL, NULL, NULL, NULL),

('EPA Environmental Justice Collaborative Problem-Solving', 'U.S. EPA', '66.306', 'federal',
 'Supports collaborative approaches to address environmental and public health issues in overburdened communities.',
 1000000, 'https://www.epa.gov/environmentaljustice/environmental-justice-collaborative-problem-solving-cooperative-agreement',
 NULL, NULL, 40.0, NULL, NULL, NULL, NULL),

('HUD Choice Neighborhoods Initiative', 'HUD', '14.889', 'federal',
 'Transforms distressed HUD-assisted housing and surrounding neighborhoods through planning and implementation grants.',
 50000000, 'https://www.hud.gov/program_offices/public_indian_housing/programs/ph/cn',
 25.0, NULL, NULL, 40.0, NULL, NULL, NULL),

('Healthy Start Initiative', 'HHS / HRSA / Maternal and Child Health Bureau', '93.926', 'federal',
 'Reduces infant mortality and improves perinatal outcomes in communities with high rates of poverty and health disparities.',
 1500000, 'https://mchb.hrsa.gov/programs-impact/healthy-start',
 20.0, NULL, 30.0, NULL, NULL, NULL, NULL),

('WIOA Adult Employment and Training Activities', 'U.S. Department of Labor', '17.258', 'federal',
 'Workforce training, job placement, and career services for adults facing barriers to employment.',
 NULL, 'https://www.dol.gov/agencies/eta/wioa',
 NULL, NULL, NULL, NULL, 8.0, NULL, NULL),

('Title I Part A — Improving Basic Programs', 'U.S. Department of Education', '84.010', 'federal',
 'Funding to schools and districts with high concentrations of poverty to close achievement gaps.',
 NULL, 'https://www.ed.gov/programs/titleiparta',
 20.0, NULL, NULL, NULL, NULL, NULL, 30.0),

('HUD Section 4 Capacity Building for Affordable Housing', 'HUD', '14.252', 'federal',
 'Builds the capacity of community development organizations to develop and preserve affordable housing.',
 NULL, 'https://www.hud.gov/program_offices/comm_planning/section4',
 NULL, 75000, NULL, 30.0, NULL, NULL, NULL),

('EPA Brownfields Assessment Grants', 'U.S. EPA', '66.818', 'federal',
 'Funds assessment and cleanup planning for contaminated brownfield sites in economically distressed areas.',
 500000, 'https://www.epa.gov/brownfields/brownfields-grant-programs',
 15.0, NULL, NULL, NULL, NULL, NULL, NULL),

('USDA SNAP Outreach and Access', 'USDA / Food and Nutrition Service', '10.580', 'federal',
 'Funding to increase participation in SNAP among eligible low-income individuals and families.',
 NULL, 'https://www.fns.usda.gov/snap/outreach',
 15.0, NULL, NULL, NULL, NULL, NULL, NULL),

('Fair Housing Initiatives Program (FHIP)', 'HUD', '14.408', 'federal',
 'Supports private fair housing enforcement, education, and outreach in communities with high renter populations.',
 NULL, 'https://www.hud.gov/program_offices/fair_housing_equal_opp/partners/FHIP',
 NULL, NULL, 30.0, 30.0, NULL, NULL, NULL),

('SBA Community Advantage Loan Program', 'U.S. Small Business Administration', '59.049', 'federal',
 'Mission-driven lenders provide 7(a) loans up to $350K in underserved markets with limited access to capital.',
 350000, 'https://www.sba.gov/funding-programs/loans/community-advantage-loans',
 NULL, 75000, NULL, NULL, NULL, NULL, NULL),

('MN DEED Pathways to Prosperity Grant', 'Minnesota Department of Employment and Economic Development',
 NULL, 'state',
 'Supports workforce development partnerships serving Minnesotans with barriers to employment in low-income communities.',
 500000, 'https://mn.gov/deed/business/financial-assistance/',
 NULL, 65000, NULL, NULL, 8.0, NULL, NULL),

('MN Housing Finance Agency Challenge Program', 'Minnesota Housing Finance Agency',
 NULL, 'state',
 'Funds affordable rental and homeownership developments for low-income Minnesotans, prioritizing communities of color.',
 2000000, 'https://www.mnhousing.gov/sites/multifamily/challengeprogram',
 NULL, 65000, 30.0, 30.0, NULL, NULL, NULL),

('Metropolitan Council Livable Communities Grant', 'Metropolitan Council of the Twin Cities',
 NULL, 'state',
 'Funds affordable housing production and remediation of polluted land for development in the seven-county MSP metro.',
 1500000, 'https://metrocouncil.org/Communities/Services/Livable-Communities-Grants.aspx',
 NULL, 75000, NULL, 30.0, NULL, 500, NULL);
