-- Restaurant chain domain. Follows the blueprint's tables (location, menu_item, ingredient, recipe, sale, inventory_lot,
-- supplier_order, prep_task, waste_event, forecast, promotion, decision_record); additions are marked (+). Sales are one
-- row per store, item and business day with the 48 fifteen-minute slots as bounded arrays per channel, never a row per
-- ticket. Every table is tenant-scoped with row-level security.

CREATE TABLE chains (                                -- (+) the tenant's chain and the simulator behind the demo
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                        -- (+) the generator's seed: the demo's synthetic chain
  start_date date NOT NULL,
  next_day int NOT NULL,                             -- (+) the clock: days run so far (the next business day to open)
  told jsonb NOT NULL DEFAULT '[]',                  -- (+) what the generator was told (simulation truth, never read by the analysis)
  sim_state bytea NOT NULL,                          -- (+) the generator's physical state (stock on shelves); never read by the analysis
  snapshot jsonb,                                    -- (+) where the last advance started, for the replay comparison
  snapshot_state bytea,
  model_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('chains');

CREATE TABLE locations (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,                                  -- external_ref, e.g. S07
  idx int NOT NULL,                                  -- (+) position in the model's arrays
  name text NOT NULL,
  region text NOT NULL,
  format text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',              -- map position
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, idx));
SELECT enable_tenant_rls('locations');

CREATE TABLE menu_items (                            -- one chain-wide menu; location_id is for local items (none here)
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  location_id text,
  status text NOT NULL DEFAULT 'active',
  price numeric(8,2) NOT NULL,
  attributes jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('menu_items');

CREATE TABLE ingredients (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  unit text NOT NULL,
  unit_cost numeric(8,3) NOT NULL,
  shelf_life_days int NOT NULL,
  supplier text NOT NULL,
  case_size double precision NOT NULL,
  storage text NOT NULL,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('ingredients');

CREATE TABLE components (                            -- (+) what the kitchen preps from ingredients
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  unit text NOT NULL,
  hold text NOT NULL CHECK (hold IN ('window', 'day')),
  labor_min_per_unit double precision NOT NULL,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('components');

CREATE TABLE recipes (                               -- bill of materials: an item from components and ingredients, a component from ingredients
  tenant_id uuid NOT NULL REFERENCES tenants,
  parent_kind text NOT NULL CHECK (parent_kind IN ('item', 'component')),
  parent_id text NOT NULL,
  input_kind text NOT NULL CHECK (input_kind IN ('component', 'ingredient')),
  input_id text NOT NULL,
  qty double precision NOT NULL,                     -- per unit of the parent, at the spec yield
  PRIMARY KEY (tenant_id, parent_kind, parent_id, input_id));
SELECT enable_tenant_rls('recipes');

-- 15-minute slot counts 10:00-22:00, one array per channel; unavailable = slots the item was 86'd (its demand is censored)
CREATE FUNCTION add_slots(a smallint[], b smallint[]) RETURNS smallint[] LANGUAGE sql IMMUTABLE AS $$
  SELECT array_agg((coalesce(x, 0) + coalesce(y, 0))::smallint ORDER BY i) FROM unnest(a, b) WITH ORDINALITY AS t(x, y, i) $$;
CREATE TABLE sales (
  tenant_id uuid NOT NULL REFERENCES tenants,
  location_id text NOT NULL,
  item_id text NOT NULL,
  business_date date NOT NULL,
  dine_in smallint[] NOT NULL CHECK (cardinality(dine_in) = 48),
  delivery smallint[] NOT NULL CHECK (cardinality(delivery) = 48),
  unavailable smallint[] NOT NULL DEFAULT '{}',      -- (+) slot indexes where the item was 86'd
  units int NOT NULL,
  revenue numeric(10,2) NOT NULL,
  discount double precision NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, location_id, item_id, business_date),
  FOREIGN KEY (tenant_id, location_id) REFERENCES locations);
CREATE INDEX sales_by_date ON sales (tenant_id, business_date);
SELECT enable_tenant_rls('sales');

CREATE TABLE pos_tickets (                           -- (+) ticket ids seen by the ingest API (replay protection)
  tenant_id uuid NOT NULL REFERENCES tenants,
  location_id text NOT NULL,
  ticket_id text NOT NULL,
  business_date date NOT NULL,
  PRIMARY KEY (tenant_id, location_id, ticket_id));
SELECT enable_tenant_rls('pos_tickets');

CREATE TABLE conditions (                            -- (+) what the weather service, the events calendar and the walk-in sensor said
  tenant_id uuid NOT NULL REFERENCES tenants,
  location_id text NOT NULL,
  business_date date NOT NULL,
  rain real[],                                       -- observed intensity by slot (0-1)
  rain_forecast real[],                              -- the latest forecast issued for the day
  event text,                                        -- a local event near the store, 17:00-21:00
  cooler_c real,                                     -- walk-in temperature, daily mean
  PRIMARY KEY (tenant_id, location_id, business_date));
SELECT enable_tenant_rls('conditions');

CREATE TABLE promotions (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  item_id text NOT NULL,
  discount double precision NOT NULL CHECK (discount > 0 AND discount < 1),
  starts_on date NOT NULL,
  ends_on date NOT NULL,                             -- exclusive
  regions text[] NOT NULL,
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('promotions');

CREATE TABLE supplier_orders (                       -- an order line: one store, one ingredient, one delivery
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  location_id text NOT NULL,
  supplier text NOT NULL,
  ingredient_id text NOT NULL,
  ordered_on date NOT NULL,
  due_on date NOT NULL,
  eta date,                                          -- (+) after a supplier's delay notice
  qty double precision NOT NULL,
  par_qty double precision,                          -- (+) what the chain's usual par ordering would have ordered
  unit_cost numeric(8,3) NOT NULL,
  status text NOT NULL CHECK (status IN ('auto_approved', 'proposed', 'approved', 'rejected', 'fallback_par', 'superseded', 'placed')),
  source text NOT NULL,                              -- history, planner, auto (the planner running unattended inside its limit)
  placed boolean NOT NULL DEFAULT false,             -- (+) sent to the supplier
  delivered_on date,                                 -- (+)
  recommendation_id uuid,
  evidence jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX orders_open ON supplier_orders (tenant_id, ordered_on, status);
CREATE INDEX orders_pipeline ON supplier_orders (tenant_id) WHERE placed AND delivered_on IS NULL;
SELECT enable_tenant_rls('supplier_orders');

CREATE TABLE recommendations (                       -- (+) one run of the order recommender
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  as_of date NOT NULL,                               -- orders placed at this day's close
  summary jsonb NOT NULL,
  decision_id uuid,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('recommendations');

CREATE TABLE inventory_lots (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,                                  -- store:ingredient:received date (one delivery a day per ingredient)
  location_id text NOT NULL,
  ingredient_id text NOT NULL,
  received_on date NOT NULL,
  expires_on date NOT NULL,                          -- the printed date: thrown away at that day's close
  qty_received double precision NOT NULL,
  qty_on_hand double precision NOT NULL,             -- from the closing lot check
  status text NOT NULL CHECK (status IN ('open', 'used', 'spoiled', 'expired')),
  closed_on date,
  PRIMARY KEY (tenant_id, id));
CREATE INDEX lots_open ON inventory_lots (tenant_id, status, location_id);
SELECT enable_tenant_rls('inventory_lots');

CREATE TABLE inventory_counts (                      -- (+) the closing count, and the usage it implies
  tenant_id uuid NOT NULL REFERENCES tenants,
  location_id text NOT NULL,
  ingredient_id text NOT NULL,
  business_date date NOT NULL,
  counted double precision NOT NULL,
  received double precision NOT NULL,
  lot_waste double precision NOT NULL,               -- spoiled or expired, logged by the staff
  actual_use double precision NOT NULL,              -- yesterday's count + received - today's count - lot waste
  theoretical_use double precision NOT NULL,         -- sales x recipes + prep discards, at spec
  PRIMARY KEY (tenant_id, location_id, ingredient_id, business_date));
SELECT enable_tenant_rls('inventory_counts');

CREATE TABLE prep_plans (                            -- (+) one plan per business day; a re-plan supersedes the last
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  business_date date NOT NULL,
  forecast_run_id uuid,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
  summary jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('prep_plans');

CREATE TABLE prep_tasks (
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  plan_id uuid,                                      -- null: the kitchen's own par sheet (history)
  location_id text NOT NULL,
  business_date date NOT NULL,
  prep_window text NOT NULL CHECK (prep_window IN ('lunch', 'dinner')),
  component_id text NOT NULL,
  qty double precision NOT NULL,
  ready_by time NOT NULL,
  labor_min double precision NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL CHECK (status IN ('planned', 'superseded', 'done')),
  done_qty double precision,                         -- (+) what was made, top-ups included
  discarded double precision,                        -- (+) what was thrown away at the end of its hold
  topups int);
CREATE INDEX prep_by_day ON prep_tasks (tenant_id, business_date, status);
SELECT enable_tenant_rls('prep_tasks');

CREATE TABLE waste_events (
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  location_id text NOT NULL,
  business_date date NOT NULL,
  kind text NOT NULL CHECK (kind IN ('ingredient', 'component')),
  ref_id text NOT NULL,
  lot_id text,
  qty double precision NOT NULL,
  reason text NOT NULL CHECK (reason IN ('spoiled', 'expired', 'prep_discard')),
  cost numeric(10,2) NOT NULL);
CREATE INDEX waste_by_day ON waste_events (tenant_id, business_date);
SELECT enable_tenant_rls('waste_events');

CREATE TABLE forecast_runs (                         -- (+) one refresh of the forecast for the whole chain
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  dates date[] NOT NULL,
  model_version text NOT NULL,
  inputs_hash text NOT NULL,
  weather_seen jsonb NOT NULL,
  duration_ms double precision NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('forecast_runs');

CREATE TABLE forecasts (                             -- mean and 90% interval per 15-minute slot, both channels together
  tenant_id uuid NOT NULL REFERENCES tenants,
  run_id uuid NOT NULL REFERENCES forecast_runs,
  location_id text NOT NULL,
  item_id text NOT NULL,
  business_date date NOT NULL,
  mean real[] NOT NULL,
  lo real[] NOT NULL,
  hi real[] NOT NULL,
  delivery_mean real[] NOT NULL,
  PRIMARY KEY (tenant_id, run_id, location_id, item_id, business_date));
SELECT enable_tenant_rls('forecasts');

CREATE TABLE notices (                               -- (+) what suppliers and the weather service told the chain
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  kind text NOT NULL CHECK (kind IN ('supplier_delay', 'weather_forecast')),
  received_on date NOT NULL,
  detail jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('notices');

CREATE TABLE alerts (                                -- (+) shrinkage cases and walk-in temperature
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  kind text NOT NULL CHECK (kind IN ('shrinkage', 'cooler')),
  location_id text NOT NULL,
  detail jsonb NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  raised_on date NOT NULL);
SELECT enable_tenant_rls('alerts');

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

-- Every online inference and plan: model version and a hash of its inputs, never the raw inputs.
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

CREATE TABLE decisions (                             -- decision_record: order changes above the limit, proposed then approved or rejected
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  kind text NOT NULL CHECK (kind IN ('order_change')),
  recommendation_id uuid NOT NULL REFERENCES recommendations,
  lines int NOT NULL,
  value_usd double precision NOT NULL,
  rationale jsonb NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected', 'superseded')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('decisions');

CREATE TABLE outcomes (                              -- (+) replays of the days just run under other plans
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  from_day date NOT NULL,
  days int NOT NULL,
  result jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
SELECT enable_tenant_rls('outcomes');
