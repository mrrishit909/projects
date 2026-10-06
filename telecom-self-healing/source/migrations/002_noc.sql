-- Network operations domain. Follows the blueprint's tables (site, sector, cell, device, link, metric_sample, alarm, incident,
-- topology_edge, configuration, recommendation, change_plan); additions are marked (+). Every table is tenant-scoped with
-- row-level security. Telemetry is time-partitioned; in production it belongs in a columnar store (see the README).

CREATE TABLE networks (                               -- (+) one synthetic metro per tenant: the generator's seed and clock
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                       -- (+) the generator's seed
  next_t int NOT NULL,                              -- (+) the clock: 15-minute intervals processed so far
  start_at timestamptz NOT NULL,                    -- (+) interval 0
  history_intervals int NOT NULL,
  told jsonb NOT NULL DEFAULT '[]',                 -- (+) what the generator was told (faults, applied changes); never read by the analysis
  rerouted text[] NOT NULL DEFAULT '{}',            -- (+) sites currently on their standby link
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('networks');

CREATE TABLE device (                                 -- core and aggregation routers, cell-site routers
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('core', 'agg', 'csr')),
  site_id text,
  cluster text,
  x double precision, y double precision,
  status text NOT NULL DEFAULT 'up',
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('device');

CREATE TABLE site (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  cluster text NOT NULL,
  role text NOT NULL CHECK (role IN ('hub', 'tail')),
  area text NOT NULL,
  x double precision NOT NULL, y double precision NOT NULL,
  parent text NOT NULL,                             -- primary backhaul parent (a hub site or an aggregation router)
  link_id text NOT NULL,
  alt_parent text,                                  -- standby microwave link, if any
  alt_link_id text,
  protected boolean NOT NULL DEFAULT false,         -- (+) e.g. a hospital: automation may not move its traffic
  label text,
  metadata jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('site');

CREATE TABLE sector (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  site_id text NOT NULL,
  azimuth double precision NOT NULL,
  status text NOT NULL DEFAULT 'up',
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES site);
SELECT enable_tenant_rls('sector');

CREATE TABLE cell (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  sector_id text NOT NULL,
  site_id text NOT NULL,
  band text NOT NULL,
  capacity_mbps double precision NOT NULL,
  status text NOT NULL DEFAULT 'up',
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, sector_id) REFERENCES sector);
SELECT enable_tenant_rls('cell');

CREATE TABLE link (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  a_device text NOT NULL,                           -- near end (towards the cells)
  b_device text NOT NULL,                           -- far end (towards the core)
  medium text NOT NULL CHECK (medium IN ('fibre', 'mw')),
  role text NOT NULL CHECK (role IN ('uplink', 'primary', 'alternate')),
  capacity_mbps double precision NOT NULL,          -- nominal
  active boolean NOT NULL DEFAULT true,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('link');

CREATE TABLE topology_edge (                          -- the graph: backhaul (site -> parent over a link) and neighbour relations
  tenant_id uuid NOT NULL REFERENCES tenants,
  src text NOT NULL,
  dst text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('backhaul', 'standby', 'neighbour')),
  via text,                                         -- the link, for backhaul edges
  weight double precision,                          -- share of handovers, for neighbour edges
  active boolean NOT NULL DEFAULT true,
  PRIMARY KEY (tenant_id, src, dst, kind));
SELECT enable_tenant_rls('topology_edge');

-- Counters every 15 minutes, one bounded array per element and interval (cells: world.CELL_KPIS, links: world.LINK_KPIS).
-- Partitioned by month; partitions are only reachable through the parent, where the tenant policy applies.
CREATE TABLE metric_sample (
  tenant_id uuid NOT NULL REFERENCES tenants,
  element_id text NOT NULL,
  t int NOT NULL,
  ts timestamptz NOT NULL,
  source text NOT NULL DEFAULT 'oss',               -- (+) oss counters or an external probe
  kind text NOT NULL CHECK (kind IN ('cell', 'link')),
  kpis real[] NOT NULL,
  anomaly real,                                     -- (+) Mahalanobis distance from the cell's seasonal normal
  flagged boolean NOT NULL DEFAULT false,           -- (+) anomalous two intervals running (cells) / unhealthy (links)
  PRIMARY KEY (tenant_id, element_id, ts, source)) PARTITION BY RANGE (ts);
CREATE TABLE metric_sample_2026_09 PARTITION OF metric_sample FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE metric_sample_2026_10 PARTITION OF metric_sample FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE metric_sample_2026_11 PARTITION OF metric_sample FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE metric_sample_default PARTITION OF metric_sample DEFAULT;
CREATE INDEX metric_by_t ON metric_sample (tenant_id, t, kind);
SELECT enable_tenant_rls('metric_sample');
REVOKE ALL ON metric_sample_2026_09, metric_sample_2026_10, metric_sample_2026_11, metric_sample_default FROM app_rw;

CREATE TABLE incident (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  opened_t int NOT NULL,
  last_t int NOT NULL,
  status text NOT NULL CHECK (status IN ('open', 'resolved', 'merged')),
  merged_into uuid,
  kind text NOT NULL,                               -- transport, power, handover, silent, radio, congestion
  root_element text NOT NULL,
  confidence double precision NOT NULL,
  alarm_count int NOT NULL,
  element_count int NOT NULL,
  ranking jsonb NOT NULL,                           -- every candidate root with its evidence
  baseline_top jsonb NOT NULL DEFAULT '[]',         -- (+) the most-alarmed elements, for comparison
  ticket_root_cause text,                           -- (+) the closed ticket's root cause (history only)
  model_versions jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX incident_open ON incident (tenant_id, status, last_t);
SELECT enable_tenant_rls('incident');

CREATE TABLE alarm (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  element_id text NOT NULL,
  t int NOT NULL,
  raised_at timestamptz NOT NULL,
  type text NOT NULL,
  severity text NOT NULL,
  related_element text,                             -- e.g. the neighbour a handover fails towards
  source text NOT NULL DEFAULT 'element',           -- element (vendor), anomaly-detection (this service), probe
  incident_id uuid);
CREATE INDEX alarm_by_t ON alarm (tenant_id, t);
CREATE INDEX alarm_by_incident ON alarm (tenant_id, incident_id);
SELECT enable_tenant_rls('alarm');

CREATE TABLE configuration (                          -- the configuration change log
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  element_id text NOT NULL,
  t int NOT NULL,
  at timestamptz NOT NULL,
  parameter text NOT NULL,
  old_value text,
  new_value text NOT NULL,
  changed_by text NOT NULL,
  change_plan_id uuid);
CREATE INDEX configuration_by_element ON configuration (tenant_id, element_id, t);
SELECT enable_tenant_rls('configuration');

CREATE TABLE policy_envelope (                        -- (+) what automation may do, versioned
  tenant_id uuid NOT NULL REFERENCES tenants,
  version int NOT NULL,
  envelope jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, version));
SELECT enable_tenant_rls('policy_envelope');

CREATE TABLE recommendation (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  incident_id uuid NOT NULL REFERENCES incident,
  kind text NOT NULL CHECK (kind IN ('reroute', 'rollback', 'none')),
  actions jsonb NOT NULL,
  inside_envelope boolean NOT NULL,
  result jsonb NOT NULL,                            -- candidates, twin series, expected impact, evidence
  policy_version int NOT NULL,
  model_versions jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('recommendation');

CREATE TABLE twin_run (                               -- (+) a what-if through the digital twin
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  from_t int NOT NULL,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  inside_envelope boolean NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('twin_run');

CREATE TABLE change_plan (                            -- decision_record: a plan proposed, then approved or rejected, then applied
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  recommendation_ids uuid[] NOT NULL DEFAULT '{}',
  actions jsonb NOT NULL,
  policy_check jsonb NOT NULL,                      -- the envelope check at proposal (and at approval)
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected', 'applied')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  applied_t int,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('change_plan');

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
