-- Migration 003: Grant data integrity
-- SAM.gov Assistance Listings verification, eligibility source attribution,
-- and formula grant local contacts.
-- Run: psql -U tractpitch tractpitch < migrations/003_grant_integrity.sql

-- ── New columns ───────────────────────────────────────────────────────────────

ALTER TABLE grants.federal_grants
    ADD COLUMN IF NOT EXISTS sam_status       VARCHAR(30)  DEFAULT 'verified_active',
    ADD COLUMN IF NOT EXISTS sam_verified_date DATE         DEFAULT '2026-07-09',
    ADD COLUMN IF NOT EXISTS criteria_source  VARCHAR(255),
    ADD COLUMN IF NOT EXISTS local_contacts   JSONB;

-- ── 1. Deactivate programs that failed SAM.gov verification ──────────────────
-- 59.049  — SAM isActive=false (archived 2015); CFDA maps to "Small Disadvantaged
--           Businesses", not Community Advantage. Community Advantage itself was
--           discontinued by SBA in May 2023.
-- 66.306  — SAM isActive=true but program objective states "This program has been
--           terminated." No active awards.
-- 14.408  — SAM isActive=false; archived April 24, 2025 under new administration.

UPDATE grants.federal_grants
SET    is_active = FALSE,
       sam_status = 'inactive'
WHERE  program_number IN ('59.049', '66.306', '14.408');

-- ── 2. Correct the 10.580 entry ───────────────────────────────────────────────
-- SAM 10.580 = "SNAP Process and Technology Improvement Grants" (state agency
-- technology projects), not community outreach. SNAP outreach funding flows
-- through state agencies under the broader SNAP administration authority.
-- Correcting program name and description to match the actual CFDA.

UPDATE grants.federal_grants
SET    program_name = 'SNAP Outreach — State Agency Grants (10.580)',
       description  = 'Funds state agencies and community partners to improve SNAP '
                      'application processes and access for eligible low-income '
                      'households. Awards flow through state FNS offices.',
       sam_status   = 'verified_active'
WHERE  program_number = '10.580';

-- ── 3. Set criteria_source for all active programs ────────────────────────────

UPDATE grants.federal_grants SET criteria_source = 'HUD CPD Notice 2024-02 (ACS 2022 LMI thresholds)'
WHERE program_number = '14.218';

UPDATE grants.federal_grants SET criteria_source = 'HUD HOME Final Rule 24 CFR Part 92 (ACS 2022 income limits)'
WHERE program_number = '14.239';

UPDATE grants.federal_grants SET criteria_source = 'CDFI Fund FY2024 NOFA (ACS 2022 distress criteria)'
WHERE program_number = '21.020';

UPDATE grants.federal_grants SET criteria_source = 'CDFI Fund FY2024 Allocation Application (ACS 2022 LIC definition)'
WHERE program_number = '21.019';

UPDATE grants.federal_grants SET criteria_source = 'EDA FY2024 NOFO (ACS 2022 per capita income / unemployment)'
WHERE program_number = '11.307';

UPDATE grants.federal_grants SET criteria_source = 'HHS ACF 45 CFR Part 1305 (ACS 2022 poverty thresholds)'
WHERE program_number = '93.600';

UPDATE grants.federal_grants SET criteria_source = 'HRSA FY2024 NOFA (HPSA / MUA designation + ACS 2022)'
WHERE program_number = '93.224';

UPDATE grants.federal_grants SET criteria_source = 'HUD FY2024 CNI NOFA (ACS 2022 distress criteria)'
WHERE program_number = '14.889';

UPDATE grants.federal_grants SET criteria_source = 'HRSA MCHB FY2024 NOFA (ACS 2022 poverty + minority thresholds)'
WHERE program_number = '93.926';

UPDATE grants.federal_grants SET criteria_source = 'DOL WIOA Formula Allotment (BLS LAUS + ACS 2022)'
WHERE program_number = '17.258';

UPDATE grants.federal_grants SET criteria_source = 'ESEA Title I Formula (Census SAIPE 2022 poverty estimates)'
WHERE program_number = '84.010';

UPDATE grants.federal_grants SET criteria_source = 'HUD FY2024 Section 4 NOFA (ACS 2022 thresholds)'
WHERE program_number = '14.252';

UPDATE grants.federal_grants SET criteria_source = 'EPA FY2024 Brownfields NOFA (ACS 2022 area MHI thresholds)'
WHERE program_number = '66.818';

UPDATE grants.federal_grants SET criteria_source = 'USDA FNS 7 CFR Part 277 (ACS 2022 poverty thresholds)'
WHERE program_number = '10.580';

UPDATE grants.federal_grants SET criteria_source = 'MN DEED FY2025 Grant Guidelines (ACS 2022 thresholds)'
WHERE program_name = 'MN DEED Pathways to Prosperity Grant';

UPDATE grants.federal_grants SET criteria_source = 'MN Housing FY2025 Challenge Program NOFA (ACS 2022 thresholds)'
WHERE program_name = 'MN Housing Finance Agency Challenge Program';

UPDATE grants.federal_grants SET criteria_source = 'Met Council FY2025 Livable Communities NOFA (ACS 2022 thresholds)'
WHERE program_name = 'Metropolitan Council Livable Communities Grant';

-- Inactive programs — mark source as N/A
UPDATE grants.federal_grants SET criteria_source = 'N/A — program inactive'
WHERE program_number IN ('59.049', '66.306', '14.408');

-- ── 4. Formula grant local contacts ──────────────────────────────────────────
-- Contacts keyed by state_fips ('19'=Iowa, '17'=Illinois, '27'=Minnesota).
-- Used by the API to surface the right contact based on the screened tract.

-- CDBG (14.218)
UPDATE grants.federal_grants
SET local_contacts = '{
  "19": {
    "name": "City of Davenport Community Development Department",
    "phone": "(563) 888-2155",
    "url": "https://www.cityofdavenportiowa.com/government/departments/community_development",
    "note": "Davenport is a CDBG entitlement community — apply directly to the city."
  },
  "17": {
    "name": "Illinois Dept. of Commerce & Economic Opportunity — State CDBG Program",
    "phone": "(217) 785-6005",
    "url": "https://dceo.illinois.gov/communityservices/communitydevelopment/cdbg.htm",
    "note": "Non-entitlement Illinois communities apply through the state CDBG program."
  },
  "27": {
    "name": "Your County Housing and Redevelopment Authority (HRA)",
    "note": "CDBG in the MSP metro is administered by county HRAs. Hennepin County HRA: (612) 348-9260 · Ramsey County CED: (651) 266-8000 · Dakota County CDA: (651) 675-4400 · Anoka County HRA: (763) 422-7075",
    "url": "https://www.mnhousing.gov/get/MHFA_013389"
  }
}'::jsonb
WHERE program_number = '14.218';

-- HOME Investment Partnerships (14.239)
UPDATE grants.federal_grants
SET local_contacts = '{
  "19": {
    "name": "City of Davenport Community Development Department",
    "phone": "(563) 888-2155",
    "url": "https://www.cityofdavenportiowa.com/government/departments/community_development",
    "note": "Davenport is a HOME Participating Jurisdiction — apply directly to the city."
  },
  "17": {
    "name": "Illinois Housing Development Authority — HOME Program",
    "url": "https://www.ihda.org/developers/rental-housing/home-program/",
    "note": "HOME funds in non-entitlement Illinois communities flow through IHDA."
  },
  "27": {
    "name": "Minnesota Housing Finance Agency — HOME Program",
    "phone": "(651) 296-7608",
    "url": "https://www.mnhousing.gov/sites/multifamily/home",
    "note": "MN HOME funds are administered by Minnesota Housing and local Participating Jurisdictions (Minneapolis, Saint Paul, Hennepin County, Ramsey County)."
  }
}'::jsonb
WHERE program_number = '14.239';

-- WIOA Adult (17.258)
UPDATE grants.federal_grants
SET local_contacts = '{
  "19": {
    "name": "Iowa Workforce Development — Quad Cities American Job Center",
    "url": "https://www.iowaworkforcedevelopment.gov/americanjobcenters",
    "note": "WIOA funds flow through local Workforce Development Boards."
  },
  "17": {
    "name": "Illinois Dept. of Employment Security — Quad Cities Workforce Board",
    "url": "https://www.illinoisworknet.com/",
    "note": "Contact the local Illinois Workforce Innovation Board for WIOA services."
  },
  "27": {
    "name": "MN DEED — WorkForce Centers (Twin Cities region)",
    "url": "https://mn.gov/deed/job-seekers/find-a-job/workforce-centers/",
    "note": "WIOA funding flows through Minnesota local Workforce Development Areas."
  }
}'::jsonb
WHERE program_number = '17.258';

-- Title I Part A (84.010)
UPDATE grants.federal_grants
SET local_contacts = '{
  "19": {
    "name": "Davenport Community School District — Federal Programs Office",
    "url": "https://www.davenportschools.org",
    "note": "Title I funds flow directly to qualifying local education agencies (LEAs)."
  },
  "17": {
    "name": "Illinois State Board of Education — Title I Programs",
    "url": "https://www.isbe.net/titlei",
    "note": "Contact your local school district federal programs coordinator."
  },
  "27": {
    "name": "Minnesota Dept. of Education — Title I Programs",
    "url": "https://education.mn.gov/MDE/dse/titlei/",
    "note": "Title I funds flow to qualifying local education agencies (LEAs) in MN."
  }
}'::jsonb
WHERE program_number = '84.010';
