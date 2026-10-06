-- Voyage domain. Follows the blueprint's tables (vessel, voyage, position, weather_cell, engine_sample, fuel_sample,
-- port_call, route_plan, speed_plan, bunker_plan, voyage_event, model_artifact, decision_record); additions are marked (+).
-- High-frequency telemetry is bounded here: hourly engine samples and AIS positions for live voyages, six-hourly
-- positions for the history, and forecast snapshots as one array per valid time, never a row per grid cell.
-- Every table is tenant-scoped with row-level security.

CREATE TABLE fleets (                               -- (+) the operator's fleet and the simulator behind it
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                       -- the generator's seed: the demo's synthetic ocean and ships
  clock_h double precision NOT NULL,                -- hours since the epoch the API maps to a date
  told jsonb NOT NULL DEFAULT '[]',                 -- storms and congestion the generator was told about (simulation truth, never read by the planners)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('fleets');

CREATE TABLE vessel (
  vessel_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  external_ref text NOT NULL,
  name text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',             -- particulars: design and service speed, MCR, DWT, TEU, tank, the sea-trial curve
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_ref));
SELECT enable_tenant_rls('vessel');

CREATE TABLE voyage (
  voyage_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  vessel_id uuid NOT NULL REFERENCES vessel,
  ref text NOT NULL,
  status text NOT NULL CHECK (status IN ('completed', 'planned', 'underway', 'berthed')),
  orig text NOT NULL,                               -- (+) UN/LOCODE of the departure and arrival ports
  dest text NOT NULL,
  departure_at timestamptz NOT NULL,
  attributes jsonb NOT NULL DEFAULT '{}',           -- charter terms: hire, berth window, late penalty, ETA tolerance; load
  state jsonb NOT NULL DEFAULT '{}',                -- (+) where the ship is on its active plan, fuel so far
  active_plan_id uuid,                              -- (+) the speed plan the ship is sailing
  notified_eta_at timestamptz,                      -- (+) the ETA last given to the charterer
  report jsonb,                                     -- (+) the voyage report at berthing
  observed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, ref));
CREATE INDEX voyage_by_vessel ON voyage (tenant_id, vessel_id, departure_at);
SELECT enable_tenant_rls('voyage');

CREATE TABLE position (                             -- AIS: hourly for live voyages, six-hourly for the history
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  at timestamptz NOT NULL,
  lat double precision NOT NULL,
  lon double precision NOT NULL,
  sog real NOT NULL,
  course real NOT NULL,
  PRIMARY KEY (voyage_id, at));
SELECT enable_tenant_rls('position');

CREATE TABLE engine_sample (                        -- hourly from the ship: log speed, shaft power, metered fuel, bridge observations
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  at timestamptz NOT NULL,
  hours real NOT NULL,
  stw real NOT NULL,
  power_kw real NOT NULL,
  fuel_t real NOT NULL,
  hs_obs real NOT NULL,
  wave_sector smallint NOT NULL,                    -- 0 head, 1 bow, 2 beam, 3 quarter, 4 following
  head_wind_obs real NOT NULL,                      -- m/s of relative wind from ahead (negative: from astern)
  PRIMARY KEY (voyage_id, at));
SELECT enable_tenant_rls('engine_sample');

CREATE TABLE fuel_sample (                          -- noon reports (and reports from the gateway)
  tenant_id uuid NOT NULL REFERENCES tenants,
  vessel_id uuid NOT NULL REFERENCES vessel,
  voyage_id uuid REFERENCES voyage,
  at timestamptz NOT NULL,
  hours real NOT NULL,
  stw real NOT NULL,
  sog real,
  distance_nm real,
  fuel_t real NOT NULL,
  hs_obs real NOT NULL,
  wave_sector smallint NOT NULL,
  head_wind_obs real NOT NULL,
  disp real NOT NULL,                               -- displacement as a fraction of design (from the drafts)
  days_clean real NOT NULL,                         -- days since the hull was last cleaned (maintenance record)
  lat double precision,
  lon double precision,
  source text NOT NULL DEFAULT 'noon',              -- (+) noon (generated with the voyage) or gateway
  predicted_t real,                                 -- (+) the fuel model's prediction, stored when scored
  PRIMARY KEY (vessel_id, at));
CREATE INDEX fuel_sample_voyage ON fuel_sample (tenant_id, voyage_id, at);
SELECT enable_tenant_rls('fuel_sample');

CREATE TABLE weather_cell (                         -- a forecast snapshot: one grid of sea state per valid time
  tenant_id uuid NOT NULL REFERENCES tenants,
  issued_at timestamptz NOT NULL,
  valid_at timestamptz NOT NULL,
  res_deg real NOT NULL,
  lat0 real NOT NULL,
  lon0 real NOT NULL,
  nlat int NOT NULL,
  nlon int NOT NULL,
  hs_dm smallint[] NOT NULL,                        -- significant wave height in decimetres, row-major from (lat0, lon0)
  storms jsonb NOT NULL DEFAULT '[]',               -- storm centres the forecast shows at this hour
  PRIMARY KEY (tenant_id, issued_at, valid_at));
SELECT enable_tenant_rls('weather_cell');

CREATE TABLE port_call (                            -- port intelligence: berth line-ups as the port publishes them, and calls
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  port text NOT NULL,
  voyage_id uuid REFERENCES voyage,
  kind text NOT NULL CHECK (kind IN ('lineup', 'arrival', 'berth')),
  reported_at timestamptz NOT NULL,
  ships_waiting int,
  earliest_berth_at timestamptz,
  detail jsonb NOT NULL DEFAULT '{}');
CREATE INDEX port_call_by_port ON port_call (tenant_id, port, reported_at DESC);
SELECT enable_tenant_rls('port_call');

CREATE TABLE route_plan (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  kind text NOT NULL CHECK (kind IN ('optimized', 'shortest', 'kept')),
  forecast_issued_at timestamptz NOT NULL,
  start_at timestamptz NOT NULL,
  speed_kn real NOT NULL,                           -- the speed order the route was solved at
  path jsonb NOT NULL,                              -- [[lat, lon], ...] from the start to the pilot station
  nodes int[] NOT NULL,
  distance_nm real NOT NULL,
  solve_s real,
  expanded int,
  model_version text NOT NULL,
  inputs_hash text NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('route_plan');

CREATE TABLE speed_plan (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  route_plan_id uuid NOT NULL REFERENCES route_plan,
  label text NOT NULL,
  status text NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'proposed', 'active', 'superseded', 'rejected')),
  legs jsonb NOT NULL,                              -- [[end distance nm, speed order kn], ...]
  eta jsonb NOT NULL,                               -- P10 / P50 / P90 arrival at the pilot station (hours)
  fuel jsonb NOT NULL,                              -- P10 / P50 / P90 passage fuel (t)
  expected jsonb NOT NULL,                          -- expected cost, CO2, waiting, late hours over the ensemble
  det_track jsonb NOT NULL,                         -- the plan hour by hour on the control forecast (for variance)
  berth_estimate_at timestamptz,
  within_terms boolean NOT NULL,
  why text,
  model_version text NOT NULL,
  inputs_hash text NOT NULL,
  created_by uuid NOT NULL,
  activated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX speed_plan_voyage ON speed_plan (tenant_id, voyage_id, created_at);
SELECT enable_tenant_rls('speed_plan');

CREATE TABLE bunker_plan (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  speed_plan_id uuid REFERENCES speed_plan,
  request jsonb NOT NULL,
  plan jsonb NOT NULL,
  cost_usd double precision,
  baseline_cost_usd double precision,
  model_version text NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('bunker_plan');

CREATE TABLE voyage_event (                         -- what the voyage monitor raised
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  kind text NOT NULL CHECK (kind IN ('storm_on_route', 'port_congestion', 'eta_at_risk', 'plan_activated', 'arrived', 'berthed')),
  at timestamptz NOT NULL,                          -- simulation time
  detail jsonb NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'info')),
  raised_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX voyage_event_by_voyage ON voyage_event (tenant_id, voyage_id, at);
SELECT enable_tenant_rls('voyage_event');

CREATE TABLE model_artifacts (                      -- model_artifact: per vessel fuel models with metrics and data snapshot
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  version text NOT NULL,
  data_snapshot text NOT NULL,
  feature_schema jsonb NOT NULL,
  metrics jsonb NOT NULL,
  artifact jsonb NOT NULL,
  approved boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, name, version));
SELECT enable_tenant_rls('model_artifacts');

CREATE TABLE model_runs (                           -- every inference: model version and a hash of its inputs
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  model_name text NOT NULL,
  version text NOT NULL,
  subject text NOT NULL,
  inputs_hash text NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('model_runs');

CREATE TABLE decisions (                            -- decision_record: a plan change beyond the charter terms, proposed then decided
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  speed_plan_id uuid NOT NULL REFERENCES speed_plan,
  kind text NOT NULL CHECK (kind IN ('plan_change')),
  rationale jsonb NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('decisions');

CREATE TABLE scenarios (                            -- (+) alternatives compared side by side, and their results
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  voyage_id uuid NOT NULL REFERENCES voyage,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('scenarios');
