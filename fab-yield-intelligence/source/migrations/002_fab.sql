-- Fab domain. Follows the blueprint's tables (fab, tool, chamber, recipe, lot, wafer, die_measurement, process_event,
-- defect, model_run, root_cause_case); additions are marked (+). Die results live on the wafer as one bounded array
-- (bins in a fixed die order), never as one row per die. Every table is tenant-scoped with row-level security.

CREATE TABLE fabs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                       -- (+) the generator's seed: the demo's synthetic fab
  next_lot int NOT NULL,                            -- (+) the clock: lots processed so far
  told jsonb NOT NULL DEFAULT '[]',                 -- (+) faults the generator was told about (simulation truth, never read by the analysis)
  qualification_lots int NOT NULL,                  -- (+) chamber baselines come from these first lots
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('fabs');

CREATE TABLE tools (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  step text NOT NULL,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('tools');

CREATE TABLE chambers (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  tool_id text NOT NULL,
  step text NOT NULL,
  status text NOT NULL DEFAULT 'up' CHECK (status IN ('up', 'hold')),
  baseline jsonb NOT NULL DEFAULT '{}',             -- (+) {sensor: [median, robust sd]} from the qualification week
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, tool_id) REFERENCES tools);
SELECT enable_tenant_rls('chambers');

CREATE TABLE recipes (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  step text NOT NULL,
  product text NOT NULL,
  setpoints jsonb NOT NULL,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('recipes');

CREATE TABLE lots (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  lot_index int NOT NULL,
  product text NOT NULL,
  started_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'quarantined', 'released')),
  source text NOT NULL DEFAULT 'equipment',        -- (+) equipment gateway or the ingest API
  PRIMARY KEY (tenant_id, id));
CREATE INDEX lots_order ON lots (tenant_id, lot_index);
SELECT enable_tenant_rls('lots');

CREATE TABLE wafers (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  lot_id text NOT NULL,
  slot int NOT NULL CHECK (slot BETWEEN 1 AND 25),
  die_bins smallint[] NOT NULL,                     -- die_measurement: one test bin per die, fixed die order
  yield double precision NOT NULL,
  label text,                                        -- an engineer's pattern label (history only)
  pattern text,                                      -- (+) the classifier's call, or 'review'
  pattern_conf double precision,
  predicted_yield double precision,                  -- (+) before test, from the process sensors
  model_version text,
  UNIQUE (tenant_id, lot_id, slot),
  FOREIGN KEY (tenant_id, lot_id) REFERENCES lots);
CREATE INDEX wafers_pattern ON wafers (tenant_id, pattern);
SELECT enable_tenant_rls('wafers');

CREATE TABLE process_events (
  tenant_id uuid NOT NULL REFERENCES tenants,
  wafer_id uuid NOT NULL REFERENCES wafers,
  step text NOT NULL,
  chamber_id text NOT NULL,
  recipe_id text NOT NULL,
  at timestamptz NOT NULL,
  sensors jsonb NOT NULL,                            -- trace summary statistics (SECS/GEM-style)
  PRIMARY KEY (wafer_id, step));
CREATE INDEX process_by_chamber ON process_events (tenant_id, chamber_id, at);
SELECT enable_tenant_rls('process_events');

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

-- Every online inference: model version and a hash of its inputs, never the raw inputs.
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

CREATE TABLE alerts (                                -- (+) what the alert-service raised
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  kind text NOT NULL CHECK (kind IN ('excursion', 'drift')),
  pattern text,
  chamber_id text,
  first_lot int NOT NULL,
  detail jsonb NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  raised_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('alerts');

CREATE TABLE root_cause_cases (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  alert_id uuid REFERENCES alerts,
  pattern text NOT NULL,
  window_lots int[] NOT NULL,
  ranking jsonb NOT NULL,
  top_chamber text NOT NULL,
  confidence double precision NOT NULL,
  affected_lots text[] NOT NULL,
  estimated_drift jsonb NOT NULL,
  model_versions jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('root_cause_cases');

CREATE TABLE decisions (                             -- decision_record: a quarantine proposed, then approved or rejected
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  case_id uuid NOT NULL REFERENCES root_cause_cases,
  kind text NOT NULL CHECK (kind IN ('quarantine')),
  lots text[] NOT NULL,
  hold_chamber text,
  rationale jsonb NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('decisions');

CREATE TABLE scenarios (                             -- (+) counterfactual runs and their results
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  case_id uuid REFERENCES root_cause_cases,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('scenarios');
