-- FinOps domain. Follows the blueprint's tables (cloud_account, resource, resource_metric, cost_line, commitment,
-- recommendation, simulation, change_request, savings_measurement, policy); additions are marked (+). Every table is
-- tenant-scoped with row-level security. Utilisation and billing lines are time-partitioned; in production they belong in
-- a columnar store (see the README).

CREATE TABLE estates (                               -- (+) the synthetic multi-cloud a tenant's connectors read from
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                       -- (+) the generator's seed
  clock_day int NOT NULL,                           -- (+) days since 2026-08-10 the simulated cloud has run
  told jsonb NOT NULL DEFAULT '{"changes": [], "commitments": []}',   -- (+) what the generator was told (merged PRs, purchases); never read by the analysis
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('estates');

CREATE TABLE policy (                                -- SLO targets, abstention and review thresholds, automation switches
  tenant_id uuid PRIMARY KEY REFERENCES tenants,
  version int NOT NULL DEFAULT 1,
  rules jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('policy');

CREATE TABLE cloud_account (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  provider text NOT NULL CHECK (provider IN ('aws', 'azure', 'gcp')),
  external_ref text NOT NULL,                       -- AWS account id, Azure subscription, GCP project
  name text NOT NULL,
  credential_ref text NOT NULL,                     -- a role / identity reference; never a key or secret
  status text NOT NULL DEFAULT 'connecting' CHECK (status IN ('connecting', 'connected')),
  metadata jsonb NOT NULL DEFAULT '{}',             -- environment, region, IaC repository
  synced_through_day int,                           -- (+) billing and utilisation stored up to this simulated day
  last_sync_at timestamptz,                         -- (+) wall-clock time of the last inventory sync (freshness)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_ref));
SELECT enable_tenant_rls('cloud_account');

CREATE TABLE resource (                              -- the inventory: what the cloud APIs report
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  cloud_account_id uuid NOT NULL REFERENCES cloud_account,
  external_id text NOT NULL,                        -- instance id, ARN or resource path
  kind text NOT NULL CHECK (kind IN ('vm', 'pool', 'db', 'volume')),
  name text NOT NULL,
  status text NOT NULL CHECK (status IN ('running', 'terminated', 'deleted')),
  attributes jsonb NOT NULL DEFAULT '{}',           -- type, size, vCPU, node-pool bounds, GB, tags, Terraform address
  launched_on date NOT NULL,
  observed_at timestamptz NOT NULL,                 -- simulated time of the snapshot
  synced_at timestamptz NOT NULL,                   -- (+) wall-clock time of the snapshot
  UNIQUE (tenant_id, external_id));
CREATE INDEX resource_account ON resource (tenant_id, cloud_account_id);
SELECT enable_tenant_rls('resource');

-- Hourly utilisation, one bounded array per resource and day (24 values each): CPU and memory utilisation, units running
-- (an instance on or off, a node pool's nodes, a volume attached) and IOPS. Partitioned by month; partitions are only
-- reachable through the parent, where the tenant policy applies.
CREATE TABLE resource_metric (
  tenant_id uuid NOT NULL REFERENCES tenants,
  resource_id uuid NOT NULL,
  day date NOT NULL,
  cpu_util real[] NOT NULL,
  mem_util real[] NOT NULL,
  units real[] NOT NULL,
  io real[] NOT NULL,
  PRIMARY KEY (tenant_id, resource_id, day)) PARTITION BY RANGE (day);
CREATE TABLE resource_metric_2026_08 PARTITION OF resource_metric FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE resource_metric_2026_09 PARTITION OF resource_metric FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE resource_metric_2026_10 PARTITION OF resource_metric FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE resource_metric_2026_11 PARTITION OF resource_metric FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE resource_metric_default PARTITION OF resource_metric DEFAULT;
SELECT enable_tenant_rls('resource_metric');
REVOKE ALL ON resource_metric_2026_08, resource_metric_2026_09, resource_metric_2026_10, resource_metric_2026_11, resource_metric_default FROM app_rw;

-- CUR-style billing at daily granularity: one usage line per resource and day (effective cost after commitments), and one
-- line per commitment and day for the part of it nothing used.
CREATE TABLE cost_line (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants,
  cloud_account_id uuid NOT NULL,
  resource_id uuid,                                 -- NULL for commitment lines
  commitment_id uuid,
  day date NOT NULL,
  line_type text NOT NULL CHECK (line_type IN ('usage', 'commitment_unused')),
  service text NOT NULL,                            -- compute, kubernetes, database, storage, commitment
  usage_type text NOT NULL,                         -- e.g. BoxUsage:m6i.2xlarge, NodeUsage:n2-standard-16, VolumeUsage.gp3
  pricing_pool text NOT NULL,                       -- (+) compute:<cloud>, db:<cloud>:<type> or storage:<cloud>: what a commitment can cover
  usage_amount double precision NOT NULL,           -- instance-hours, node-hours or GB-days
  unit_price double precision NOT NULL,             -- on-demand price per unit
  on_demand_cost double precision NOT NULL,
  effective_cost double precision NOT NULL,         -- after savings plans and reservations
  PRIMARY KEY (tenant_id, day, id)) PARTITION BY RANGE (day);
CREATE TABLE cost_line_2026_08 PARTITION OF cost_line FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE cost_line_2026_09 PARTITION OF cost_line FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE cost_line_2026_10 PARTITION OF cost_line FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE cost_line_2026_11 PARTITION OF cost_line FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE cost_line_default PARTITION OF cost_line DEFAULT;
CREATE INDEX cost_line_resource ON cost_line (tenant_id, resource_id, day);
SELECT enable_tenant_rls('cost_line');
REVOKE ALL ON cost_line_2026_08, cost_line_2026_09, cost_line_2026_10, cost_line_2026_11, cost_line_default FROM app_rw;

-- Model governance: what was trained on which data and how it scored; every inference logged with version and input hash.
CREATE TABLE model_artifact (                        -- (+)
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  version text NOT NULL,
  data_snapshot text NOT NULL,
  metrics jsonb NOT NULL,
  artifact bytea,
  approved boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, name, version));
SELECT enable_tenant_rls('model_artifact');

CREATE TABLE model_run (                             -- (+)
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  model_name text NOT NULL,
  version text NOT NULL,
  subject text NOT NULL,
  inputs_hash text NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('model_run');

CREATE TABLE recommendation_run (                    -- (+) one run of the rightsizer over the estate, with the baseline's view
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  clock_day int NOT NULL,
  summary jsonb NOT NULL,
  model_versions jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('recommendation_run');

CREATE TABLE recommendation (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  run_id uuid NOT NULL REFERENCES recommendation_run,
  resource_id uuid NOT NULL REFERENCES resource,
  action text NOT NULL CHECK (action IN ('resize', 'terminate', 'delete', 'lower_min_nodes', 'review')),
  from_config jsonb NOT NULL,
  to_config jsonb NOT NULL,                         -- what the change sets: {size} | {min_nodes} | {terminate}
  monthly_savings double precision NOT NULL DEFAULT 0,
  confidence double precision,                      -- share of forecast paths in which the change keeps the SLO
  risk double precision,                            -- P(SLO breach) from the change-risk model (resizes)
  status text NOT NULL CHECK (status IN ('open', 'review', 'in_change_request', 'applied', 'superseded')),
  reason text,                                      -- why a recommendation is a review task, not an action
  evidence jsonb NOT NULL DEFAULT '{}',
  model_versions jsonb NOT NULL,
  inputs_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX recommendation_status ON recommendation (tenant_id, status);
SELECT enable_tenant_rls('recommendation');

CREATE TABLE commitment_portfolio (                  -- (+) one optimisation: the plan, its baseline and the decision on it
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected', 'purchased')),
  model_version text NOT NULL,
  inputs_hash text NOT NULL,
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('commitment_portfolio');

CREATE TABLE commitment (                            -- savings plans and reservations: proposed, approved, active
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  portfolio_id uuid REFERENCES commitment_portfolio,
  provider text NOT NULL,
  instrument text NOT NULL CHECK (instrument IN ('compute_savings_plan', 'db_reservation')),
  instance_type text,                               -- reservations only
  amount double precision NOT NULL,                 -- savings plan: on-demand $ per hour covered; reservation: instances
  hourly_fee double precision NOT NULL,
  discount double precision NOT NULL,
  term_months int NOT NULL,
  status text NOT NULL CHECK (status IN ('proposed', 'approved', 'active', 'rejected')),
  start_day int,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('commitment');

CREATE TABLE simulation (                            -- SLO-risk simulations of alternative plans
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('simulation');

CREATE TABLE change_request (                        -- a Terraform pull request: a text diff, never applied by this service
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  title text NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'opened', 'rejected', 'merged')),
  recommendation_ids uuid[] NOT NULL,
  files jsonb NOT NULL,                             -- {repository: {path: unified diff}}
  body text NOT NULL,                               -- the pull request description, with the evidence
  summary jsonb NOT NULL,
  proposed_by uuid NOT NULL,
  approved_by uuid,
  approved_at timestamptz,
  applied_day int,                                  -- (+) when the team's pipeline merged and applied it (the replay)
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('change_request');

CREATE TABLE savings_measurement (                   -- realised savings of an applied change request, by method
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  change_request_id uuid NOT NULL REFERENCES change_request,
  resource_id uuid,                                 -- NULL: the change request as a whole
  window_from date NOT NULL,
  window_to date NOT NULL,
  method text NOT NULL,
  estimate double precision NOT NULL,
  baselines jsonb NOT NULL,                         -- before/after, difference-in-differences, list price
  detail jsonb NOT NULL DEFAULT '{}',
  model_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('savings_measurement');
