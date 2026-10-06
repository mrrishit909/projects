-- Trial recruitment and site optimisation. Follows the blueprint's tables (study, criterion, site, investigator,
-- population_bucket, patient_token, eligibility_event, site_metric, site_score, portfolio_plan); additions are marked (+).
-- No table holds a name, a medical record number, a birth date, a calendar date of care or free text about a patient:
-- patient_token keeps a keyed hash, an age band, a distance band and events as days before the snapshot.
-- Every table is tenant-scoped with row-level security.

CREATE TABLE network (                               -- (+) the research network a sponsor or CRO works with
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                        -- (+) the generator's seed: the demo's synthetic network
  snapshot_date date NOT NULL,                       -- events are stored as days relative to this
  token_salt text NOT NULL,                          -- tenant secret for the keyed patient hash; never exported
  feed jsonb NOT NULL DEFAULT '{}',                  -- records received, tokenised, events refused and why
  told jsonb NOT NULL DEFAULT '[]',                  -- (+) what the simulator was asked to run (simulation truth, never read by the analysis)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('network');

CREATE TABLE site (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  region text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('academic', 'community')),
  lat double precision NOT NULL,
  lon double precision NOT NULL,
  records int NOT NULL,                              -- tokenised oncology records the site contributes
  competing_trials int NOT NULL,
  activation_cost numeric NOT NULL,
  per_patient_cost numeric NOT NULL,
  capacity int NOT NULL,                             -- slots a site will take in one study
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('site');

CREATE TABLE investigator (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  site_id text NOT NULL,
  name text NOT NULL,
  specialty text NOT NULL,
  trials_by_indication jsonb NOT NULL,
  publications_by_indication jsonb NOT NULL,
  open_gcp_finding boolean NOT NULL DEFAULT false,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES site);
SELECT enable_tenant_rls('investigator');

CREATE TABLE site_metric (                           -- one row per past study at a site: the enrolment history
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  site_id text NOT NULL,
  study_ref text NOT NULL,
  indication text NOT NULL,
  start_month int NOT NULL,                          -- months before the snapshot
  pool_estimate int NOT NULL,                        -- eligible patients the feasibility survey estimated at the time
  lead_investigator text NOT NULL,
  competing_trials int NOT NULL,
  activation_months double precision,                -- NULL: the site never opened within the enrolment window
  months_enrolling double precision NOT NULL,
  enrolled int NOT NULL,
  dropped int NOT NULL,
  FOREIGN KEY (tenant_id, site_id) REFERENCES site);
CREATE INDEX site_metric_site ON site_metric (tenant_id, site_id);
SELECT enable_tenant_rls('site_metric');

CREATE TABLE enrollee_history (                      -- (+) past enrollees' banded features and whether they dropped out
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  site_id text NOT NULL,
  study_ref text NOT NULL,
  features jsonb NOT NULL,
  dropped boolean NOT NULL);
SELECT enable_tenant_rls('enrollee_history');

CREATE TABLE patient_token (
  tenant_id uuid NOT NULL REFERENCES tenants,
  token text NOT NULL,                               -- keyed SHA-256 of the source MRN (truncated); not reversible without the salt
  site_id text NOT NULL,
  sex text NOT NULL,
  age_band text NOT NULL,
  distance_band text NOT NULL,
  timeline jsonb NOT NULL,                           -- events with day offsets, canonical units; no dates, no text
  record_hash text NOT NULL,                         -- lineage: explanations re-derive from exactly this timeline
  PRIMARY KEY (tenant_id, token),
  FOREIGN KEY (tenant_id, site_id) REFERENCES site);
CREATE INDEX patient_token_site ON patient_token (tenant_id, site_id);
SELECT enable_tenant_rls('patient_token');

CREATE TABLE study (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  external_ref text NOT NULL,
  name text,
  indication text,
  protocol_text text NOT NULL,
  text_sha256 text NOT NULL,
  status text NOT NULL DEFAULT 'in_review' CHECK (status IN ('in_review', 'approved')),
  parser_version text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_by uuid NOT NULL,
  approved_by uuid,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_ref));
SELECT enable_tenant_rls('study');

CREATE TABLE criterion (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  study_id uuid NOT NULL REFERENCES study,
  ref text NOT NULL,                                  -- I3, E2: the protocol's own numbering
  position int NOT NULL,
  type text NOT NULL CHECK (type IN ('inclusion', 'exclusion')),
  text text NOT NULL,
  proposed jsonb NOT NULL,                            -- the parser's rules (DSL)
  status text NOT NULL CHECK (status IN ('parsed', 'review', 'manual')),
  confidence double precision NOT NULL,
  reasons jsonb NOT NULL DEFAULT '[]',
  review_action text CHECK (review_action IN ('accepted', 'edited', 'manual')),
  rules jsonb,                                        -- what the reviewer approved: the rules the engine runs
  reviewed_by uuid,
  reviewed_at timestamptz,
  UNIQUE (tenant_id, study_id, ref));
SELECT enable_tenant_rls('criterion');

CREATE TABLE eligibility_event (                      -- one patient against one study's approved criteria
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  study_id uuid NOT NULL REFERENCES study,
  token text NOT NULL,
  site_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('eligible', 'potential', 'ineligible')),
  criterion_values jsonb NOT NULL,                    -- {ref: 1 | 0 | null}
  failed text[] NOT NULL,
  unknown text[] NOT NULL,
  weight double precision NOT NULL,                   -- 1, 0, or the chance a potential patient's open criteria pass
  engine_version text NOT NULL,
  criteria_hash text NOT NULL,
  record_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, study_id, token));
CREATE INDEX eligibility_by_status ON eligibility_event (tenant_id, study_id, status);
SELECT enable_tenant_rls('eligibility_event');

CREATE TABLE population_bucket (                      -- the analytics grain: counts only
  tenant_id uuid NOT NULL REFERENCES tenants,
  study_id uuid NOT NULL REFERENCES study,
  site_id text NOT NULL,
  age_band text NOT NULL,
  status text NOT NULL,
  patients int NOT NULL,
  expected_eligible double precision NOT NULL,
  PRIMARY KEY (tenant_id, study_id, site_id, age_band, status));
SELECT enable_tenant_rls('population_bucket');

CREATE TABLE site_score (
  tenant_id uuid NOT NULL REFERENCES tenants,
  study_id uuid NOT NULL REFERENCES study,
  site_id text NOT NULL,
  expected_eligible double precision NOT NULL,
  expected_enrolled double precision NOT NULL,
  p10 int NOT NULL,
  p90 int NOT NULL,
  dropout_risk double precision NOT NULL,
  expected_evaluable double precision NOT NULL,
  naive_expected double precision NOT NULL,          -- the baseline: the site's historical average per study
  excluded text,                                      -- policy: why the optimiser may not pick this site
  detail jsonb NOT NULL,                              -- activation, frailty, investigator profile, costs
  model_version text NOT NULL,
  inputs_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, study_id, site_id));
SELECT enable_tenant_rls('site_score');

CREATE TABLE portfolio_plan (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  study_id uuid NOT NULL REFERENCES study,
  request jsonb NOT NULL,
  sites text[] NOT NULL,
  result jsonb NOT NULL,                              -- expected evaluable, cost, interval, P(target), baselines, solver
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('portfolio_plan');

CREATE TABLE study_run (                               -- (+) what the simulator's 12 months of enrolment gave an approved plan
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  study_id uuid NOT NULL REFERENCES study,
  plan_id uuid NOT NULL REFERENCES portfolio_plan,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('study_run');

-- Model governance: what was trained on which data, how it scored against its baseline, and the artifact.
CREATE TABLE model_artifacts (
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  version text NOT NULL,
  data_snapshot text NOT NULL,
  metrics jsonb NOT NULL,
  artifact bytea NOT NULL,
  approved boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, name, version));
SELECT enable_tenant_rls('model_artifacts');

-- Every inference: model version and a hash of its inputs, never the raw inputs.
CREATE TABLE model_runs (
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  model_name text NOT NULL,
  version text NOT NULL,
  subject text NOT NULL,
  inputs_hash text NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('model_runs');
