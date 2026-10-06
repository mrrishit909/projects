-- Mining domain. Follows the blueprint's tables (mine, block, bench, haul_road, vehicle, shovel, stockpile, assay, haul_event,
-- plant_feed, blend_plan, simulation_run) and its decision_record; additions are marked (+). Every table is tenant-scoped with
-- row-level security. Engine telemetry is time-partitioned; in production it belongs in a time-series store (see the README).

CREATE TABLE mine (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                       -- (+) the generator's seed: the demo's synthetic mine
  start_at timestamptz NOT NULL,                    -- (+) minute 0 of shift 0
  clock_min double precision NOT NULL,              -- (+) minutes since start_at that have been simulated and ingested
  history_shifts int NOT NULL,
  told jsonb NOT NULL DEFAULT '[]',                 -- (+) what the generator was told (a low-grade zone, breakdowns); never read by the analysis
  sim_state jsonb NOT NULL,                         -- (+) the generator's start-of-shift state and plan schedule; never read by the analysis
  plant jsonb NOT NULL,                             -- (+) the concentrator's contract: grade window, arsenic limit, prices
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('mine');

CREATE TABLE bench (
  tenant_id uuid NOT NULL REFERENCES tenants,
  k int NOT NULL,
  floor_rl double precision NOT NULL,
  ramp_x double precision NOT NULL,
  ramp_y double precision NOT NULL,
  PRIMARY KEY (tenant_id, k));
SELECT enable_tenant_rls('bench');

CREATE TABLE block (                                -- the block model: one row per 10 x 10 x 15 m block, the estimate and its spread
  tenant_id uuid NOT NULL REFERENCES tenants,
  id int NOT NULL,
  bench int NOT NULL,
  i int NOT NULL,
  j int NOT NULL,
  status text NOT NULL DEFAULT 'in_situ' CHECK (status IN ('in_situ', 'mined')),
  est_cu double precision,                          -- expected %Cu (lognormal kriging)
  cu_mu double precision,                           -- log-grade posterior mean and sd
  cu_s double precision,
  est_as double precision,                          -- ppm
  as_s double precision,
  est_bwi double precision,                         -- Bond work index, kWh/t
  cls text CHECK (cls IN ('HG', 'LG', 'W')),        -- ore control: high grade, low grade, waste at the cut-offs
  p_hg double precision,                            -- (+) probability above the high-grade cut-off
  model_version text,
  observed_at timestamptz,                          -- when the estimate was last conditioned on new assays
  PRIMARY KEY (tenant_id, id));
CREATE INDEX block_bench ON block (tenant_id, bench);
SELECT enable_tenant_rls('block');

CREATE TABLE site_node (                            -- (+) the pit exit, the go-line, the crusher, the stockpiles and the dump
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  x double precision NOT NULL,
  y double precision NOT NULL,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('site_node');

CREATE TABLE haul_road (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  from_node text NOT NULL,
  to_node text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('bench', 'ramp', 'surface')),
  length_m double precision NOT NULL,
  grade double precision NOT NULL,                  -- rise over run in the direction from -> to
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('haul_road');

CREATE TABLE vehicle (                              -- haul trucks
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  model text NOT NULL,
  payload_t double precision NOT NULL,
  age_h int NOT NULL,
  status text NOT NULL DEFAULT 'up' CHECK (status IN ('up', 'down')),
  status_at timestamptz,
  last_node text,                                   -- (+) where it last dumped (the dispatcher's next decision point)
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('vehicle');

CREATE TABLE shovel (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('rope', 'hydraulic')),
  bench int NOT NULL,
  rate_tph double precision NOT NULL,               -- planning dig rate
  load_min double precision NOT NULL,               -- (+) measured spot-and-load time
  seq int[] NOT NULL,                               -- (+) the mine plan: the blocks it digs, in order
  pos int NOT NULL,                                 -- (+) index in seq of the block at the face (from the haul log)
  remaining_t double precision NOT NULL,            -- (+) tonnes left in that block
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('shovel');

CREATE TABLE stockpile (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL CHECK (id IN ('hg', 'lg')),
  tonnes double precision NOT NULL,
  cu double precision NOT NULL,                     -- estimated grade of what is on it, and the spread of that estimate
  cu_sd double precision NOT NULL,
  as_ppm double precision NOT NULL,
  as_sd double precision NOT NULL,
  bwi double precision NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('stockpile');

CREATE TABLE assay (                                -- drill-hole composites and blast-hole samples, one per block sampled
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  hole text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('exploration', 'blasthole')),
  block int NOT NULL,
  cu double precision NOT NULL,
  as_ppm double precision NOT NULL,
  bwi double precision NOT NULL,
  received_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id));
CREATE INDEX assay_block ON assay (tenant_id, block);
SELECT enable_tenant_rls('assay');

CREATE TABLE haul_event (                           -- the dispatch system's log: one row per truck cycle
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  truck text NOT NULL,
  shovel text NOT NULL,
  block int NOT NULL,
  cls text NOT NULL,
  dest text NOT NULL CHECK (dest IN ('crusher', 'hg', 'lg', 'dump')),
  from_node text NOT NULL,
  payload_t double precision NOT NULL,
  dispatched_at timestamptz NOT NULL,
  ended_at timestamptz NOT NULL,
  cycle_min double precision NOT NULL,
  segments jsonb NOT NULL,                          -- empty, queue at shovel, load, haul, queue at dump, dump (minutes)
  fuel_l double precision NOT NULL,
  dispatch_context jsonb NOT NULL,                  -- what the dispatcher saw: queue, trucks en route, trucks bound for the crusher, wet road
  plan_id uuid,
  UNIQUE (tenant_id, truck, ended_at));
CREATE INDEX haul_time ON haul_event (tenant_id, ended_at);
SELECT enable_tenant_rls('haul_event');

-- Engine telemetry: 10-minute summaries per truck, partitioned by month; partitions are reachable only through the parent's policy.
CREATE TABLE truck_telemetry (                      -- (+)
  tenant_id uuid NOT NULL,
  truck text NOT NULL,
  at timestamptz NOT NULL,
  source text NOT NULL DEFAULT 'fleet',
  state text NOT NULL CHECK (state IN ('working', 'idle', 'down')),
  duty double precision, speed_kmh double precision, payload_t double precision, loaded_frac double precision, ambient_c double precision,
  coolant_c double precision, oil_kpa double precision, exhaust_c double precision, fuel_lph double precision,
  z jsonb,                                          -- the anomaly detector's directional deviations, in sd
  PRIMARY KEY (tenant_id, truck, at, source)) PARTITION BY RANGE (at);
CREATE TABLE truck_telemetry_2026_09 PARTITION OF truck_telemetry FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE truck_telemetry_2026_10 PARTITION OF truck_telemetry FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE truck_telemetry_2026_11 PARTITION OF truck_telemetry FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE truck_telemetry_default PARTITION OF truck_telemetry DEFAULT;
SELECT enable_tenant_rls('truck_telemetry');
REVOKE ALL ON truck_telemetry_2026_09, truck_telemetry_2026_10, truck_telemetry_2026_11, truck_telemetry_default FROM app_rw;

CREATE TABLE plant_feed (                           -- one row per hour: crusher deliveries, reclaim, mill throughput, the analyser
  tenant_id uuid NOT NULL REFERENCES tenants,
  hour_at timestamptz NOT NULL,
  delivered_t double precision NOT NULL,
  reclaim_t double precision NOT NULL,
  reclaim_by_pile jsonb NOT NULL DEFAULT '{}',
  processed_t double precision NOT NULL,
  bin_start_t double precision NOT NULL,
  outage_min double precision NOT NULL,
  feed_cu double precision,
  feed_as double precision,
  est_bwi double precision,                         -- (+) the estimator's hardness of what was fed
  PRIMARY KEY (tenant_id, hour_at));
SELECT enable_tenant_rls('plant_feed');

CREATE TABLE equipment_alert (                      -- (+) maintenance-feed: engine anomalies and breakdowns
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  truck text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('anomaly', 'breakdown')),
  sensor text,
  value double precision,
  raised_at timestamptz NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')));
CREATE INDEX alert_truck ON equipment_alert (tenant_id, truck, raised_at);
SELECT enable_tenant_rls('equipment_alert');

CREATE TABLE dispatch_plan (                        -- (+) a shift's dispatch: assignments or target rates, routing, ore control, reclaim
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  kind text NOT NULL CHECK (kind IN ('baseline', 'optimized')),
  status text NOT NULL CHECK (status IN ('draft', 'proposed', 'active', 'superseded', 'rejected')),
  plan jsonb NOT NULL,
  summary jsonb NOT NULL,
  inputs_hash text NOT NULL,
  model_versions jsonb NOT NULL,
  effective_from_min double precision,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX one_active_plan ON dispatch_plan (tenant_id) WHERE status = 'active';
SELECT enable_tenant_rls('dispatch_plan');

CREATE TABLE blend_plan (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  dispatch_plan_id uuid NOT NULL REFERENCES dispatch_plan,
  hours jsonb NOT NULL,                              -- per hour: reclaim by stockpile, pit feed, blend grade and its band
  baseline jsonb NOT NULL,                           -- the proportional blend on the same pit feed
  params jsonb NOT NULL,
  objective double precision NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('blend_plan');

CREATE TABLE simulation_run (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('simulation_run');

CREATE TABLE decision_record (                      -- a plan proposed, then approved or rejected by a second person
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  subject_type text NOT NULL,
  subject_id uuid NOT NULL,
  decision_type text NOT NULL,
  model_versions jsonb NOT NULL,
  inputs_hash text NOT NULL,
  result jsonb NOT NULL,
  confidence double precision,
  policy_state jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('decision_record');

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

-- Every online inference and solve: model version and a hash of its inputs, never the raw inputs.
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
