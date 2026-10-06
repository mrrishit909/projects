-- Warehouse robotics domain. Follows the blueprint's tables (warehouse, zone, node, edge, robot, robot_state, task,
-- task_assignment, route_plan, conflict, charger, battery_cycle, simulation_run); additions are marked (+). Telemetry is
-- not kept per step: robot_state holds each robot's latest report, and a run's trajectories live only as a heat map and
-- per-bucket counts in its result. Every table is tenant-scoped with row-level security.

CREATE TABLE warehouses (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  external_ref text,
  name text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',              -- layout parameters and counts
  seed bigint NOT NULL,                              -- (+) the generator's seed: the demo's synthetic warehouse
  clock_s int NOT NULL DEFAULT 0,                    -- (+) simulated seconds since the shift's wave started
  wave jsonb,                                        -- (+) the order rate the generator was told
  told jsonb NOT NULL DEFAULT '[]',                  -- (+) events the generator was told about (simulation truth, never read by the planner)
  world_state bytea NOT NULL,                        -- (+) the floor: positions, batteries, closures (the generator's side)
  fleet_state bytea NOT NULL,                        -- (+) the orchestrator: plans, reservations, tasks, chargers
  state_version int NOT NULL DEFAULT 0,              -- (+) bumps on every change; a plan approved against an older version is stale
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id),
  UNIQUE (tenant_id, external_ref));
SELECT enable_tenant_rls('warehouses');

CREATE TABLE zones (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,                                  -- aisle A-14, cross-aisle X1, highway H2, PARK, PACK
  warehouse_id uuid NOT NULL REFERENCES warehouses,
  kind text NOT NULL CHECK (kind IN ('aisle', 'cross_aisle', 'highway', 'parking', 'pack')),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  attributes jsonb NOT NULL DEFAULT '{}',
  observed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('zones');

CREATE TABLE nodes (                                 -- one grid cell a robot can stand on
  tenant_id uuid NOT NULL REFERENCES tenants,
  id int NOT NULL,
  x int NOT NULL,
  y int NOT NULL,
  kind text NOT NULL CHECK (kind IN ('aisle', 'cross', 'lane', 'bay', 'station')),
  zone_id text NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, zone_id) REFERENCES zones);
SELECT enable_tenant_rls('nodes');

CREATE TABLE edges (                                 -- undirected, stored once with src < dst
  tenant_id uuid NOT NULL REFERENCES tenants,
  src int NOT NULL,
  dst int NOT NULL,
  PRIMARY KEY (tenant_id, src, dst),
  FOREIGN KEY (tenant_id, src) REFERENCES nodes,
  FOREIGN KEY (tenant_id, dst) REFERENCES nodes,
  CHECK (src < dst));
SELECT enable_tenant_rls('edges');

CREATE TABLE robots (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  vendor text NOT NULL,                              -- capability profile: pack size, chemistry
  home_node int NOT NULL,
  capacity_wh double precision NOT NULL,             -- nominal pack energy
  commissioned_on date NOT NULL,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('robots');

CREATE TABLE robot_state (                           -- latest report per robot only; never one row per step
  tenant_id uuid NOT NULL REFERENCES tenants,
  robot_id text NOT NULL,
  node int NOT NULL,
  soc double precision NOT NULL,
  soh_est double precision,                          -- (+) the battery model's state of health
  status text NOT NULL,
  task_id text,
  sim_t int NOT NULL,                                -- (+) simulated second of the report
  observed_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, robot_id),
  FOREIGN KEY (tenant_id, robot_id) REFERENCES robots);
SELECT enable_tenant_rls('robot_state');

CREATE TABLE chargers (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  node int NOT NULL,
  status text NOT NULL DEFAULT 'up' CHECK (status IN ('up', 'fault')),
  occupant text,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('chargers');

CREATE TABLE battery_cycles (
  tenant_id uuid NOT NULL REFERENCES tenants,
  robot_id text NOT NULL,
  cycle int NOT NULL,
  ended_at timestamptz NOT NULL,
  dod double precision NOT NULL,                     -- depth of discharge
  temp_c double precision NOT NULL,                  -- mean pack temperature over the cycle
  capacity_wh double precision NOT NULL,             -- measured at the end of the cycle
  PRIMARY KEY (tenant_id, robot_id, cycle),
  FOREIGN KEY (tenant_id, robot_id) REFERENCES robots);
SELECT enable_tenant_rls('battery_cycles');

CREATE TABLE tasks (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,                                  -- the order reference from the WMS
  pick_node int NOT NULL,
  location text NOT NULL,                            -- e.g. A-14-07
  priority text NOT NULL CHECK (priority IN ('normal', 'urgent')),
  status text NOT NULL CHECK (status IN ('open', 'assigned', 'picked', 'done', 'held')),
  released_s int NOT NULL,
  due_s int NOT NULL,
  robot_id text,
  station text,
  assigned_s int,
  picked_s int,
  done_s int,
  source text NOT NULL CHECK (source IN ('wave', 'api')),
  bumped int NOT NULL DEFAULT 0,                     -- (+) times a robot was taken off it
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
CREATE INDEX tasks_status ON tasks (tenant_id, status, priority);
SELECT enable_tenant_rls('tasks');

CREATE TABLE task_assignments (                      -- every assignment, with the policy, solver version and inputs hash
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  task_id text NOT NULL,
  robot_id text NOT NULL,
  station text NOT NULL,
  policy text NOT NULL,
  solver_version text NOT NULL,
  epoch_s int NOT NULL,
  inputs_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('task_assignments');

CREATE TABLE route_plans (                           -- each robot's current plan: a cell per second from start_s
  tenant_id uuid NOT NULL REFERENCES tenants,
  robot_id text NOT NULL,
  start_s int NOT NULL,
  path int[] NOT NULL,
  legs jsonb NOT NULL,
  planner text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, robot_id));
SELECT enable_tenant_rls('route_plans');

CREATE TABLE conflicts (                             -- conflicts the planner resolved by replanning, and any the checker found
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  sim_t int NOT NULL,
  kind text NOT NULL CHECK (kind IN ('replan', 'vertex', 'edge_swap', 'entered_closed_aisle', 'paused_robot_moved', 'not_an_edge')),
  robots text[] NOT NULL,
  node int,
  detail jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX conflicts_kind ON conflicts (tenant_id, kind, sim_t);
SELECT enable_tenant_rls('conflicts');

CREATE TABLE world_events (                          -- (+) what the orchestrator observed: closures, charger faults, pauses
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  sim_t int NOT NULL,
  kind text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('world_events');

CREATE TABLE simulation_runs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('simulation_runs');

-- Model governance: what was fitted on which data, how it scored against its baseline, and the artifact.
CREATE TABLE model_artifacts (
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  version text NOT NULL,
  data_snapshot text NOT NULL,
  metrics jsonb NOT NULL,
  artifact bytea,
  approved boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, name, version));
SELECT enable_tenant_rls('model_artifacts');

-- Every inference or solve: model version and a hash of its inputs, never the raw inputs.
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

CREATE TABLE decisions (                             -- decision_record: a high-impact plan proposed, then approved or rejected
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  kind text NOT NULL CHECK (kind IN ('preemption')),
  proposal jsonb NOT NULL,
  state_version int NOT NULL,                        -- the warehouse state the plan was computed against
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected', 'stale')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('decisions');
