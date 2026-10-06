-- Carbon accounting domain. Follows the blueprint's tables (organization, facility, supplier, supplier_alias, activity,
-- emission_factor, factor_version, calculation, calculation_lineage, scenario, assurance_evidence, decision_record);
-- additions are marked (+). Every table is tenant-scoped with row-level security.

CREATE TABLE organization (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,                                  -- 'MDG' for the group, 'MDG-DE' for a subsidiary
  parent_id text,
  external_ref text,                                 -- the ERP company code
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('group', 'subsidiary')),
  country text,
  currency text,
  metadata jsonb NOT NULL DEFAULT '{}',
  model_seed bigint,                                 -- (+) group row: the generator's seed (the demo's synthetic company)
  told jsonb NOT NULL DEFAULT '[]',                  -- (+) group row: what the generator was told (simulation truth, never read by the analysis)
  reporting_year int,                                -- (+)
  current_factor_version text,                       -- (+) the version new calculations use unless told otherwise
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, external_ref));
SELECT enable_tenant_rls('organization');

CREATE TABLE facility (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,
  organization_id text NOT NULL,
  kind text NOT NULL,
  country text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  attributes jsonb NOT NULL DEFAULT '{}',
  observed_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES organization);
SELECT enable_tenant_rls('facility');

-- A resolved supplier: one legal entity behind one or more vendor records.
CREATE TABLE supplier (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id uuid NOT NULL,
  name text NOT NULL,                                -- the most representative of its vendor records' names
  country text,
  tax_id text,
  main_category text,                                -- (+) the category most of our spend with it falls in
  records int NOT NULL,
  resolver_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('supplier');

-- Vendor records from each subsidiary's ERP vendor master; resolution points each at a supplier.
CREATE TABLE supplier_alias (
  tenant_id uuid NOT NULL REFERENCES tenants,
  vendor_ref text NOT NULL,
  subsidiary text NOT NULL,
  name text NOT NULL,
  country text,
  tax_id text,
  email_domain text,
  supplier_id uuid,
  match_prob double precision,                       -- the strongest link that put it in its cluster
  evidence jsonb NOT NULL DEFAULT '{}',              -- the pair's features and the model's weights
  PRIMARY KEY (tenant_id, vendor_ref),
  FOREIGN KEY (tenant_id, supplier_id) REFERENCES supplier);
CREATE INDEX alias_supplier ON supplier_alias (tenant_id, supplier_id);
SELECT enable_tenant_rls('supplier_alias');

CREATE TABLE import_batch (                           -- (+) one connector pull or one API upload
  tenant_id uuid NOT NULL REFERENCES tenants,
  id uuid NOT NULL,
  connector text NOT NULL,
  stats jsonb NOT NULL,
  rejected jsonb NOT NULL DEFAULT '[]',
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('import_batch');

-- Every normalised activity line: an invoice line, a shipment or a utility bill. Unique per source record, so a
-- double posting or a repeated import lands once.
CREATE TABLE activity (
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  batch_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('ap', 'freight', 'utility')),
  source_ref text NOT NULL,                          -- subsidiary:invoice:line, shipment id or bill id
  subsidiary text NOT NULL,
  facility_id text,
  vendor_ref text,
  period date NOT NULL,
  description text,
  gl_code text,
  amount double precision,                           -- as invoiced, in `currency`
  currency text,
  fx_rate double precision,                          -- USD per unit for the invoice month
  amount_usd double precision,
  quantity double precision,                         -- as billed or shipped, in `unit`
  unit text,
  qty_norm double precision,                         -- kWh, litres or tonnes
  unit_norm text,
  distance_km double precision,
  tkm double precision,
  mode text,                                         -- freight: air, ocean, road, rail
  fuel text,                                         -- utility: electricity, natural_gas, diesel
  origin text,
  destination text,
  urgent boolean,
  category text,                                     -- the spend category, or NULL (an orphan)
  category_conf real,
  mapping_method text,                               -- model, fallback (rules, sent for review) or unmapped
  input_hash text,                                   -- the classifier input's hash (model_runs has the call)
  UNIQUE (tenant_id, kind, source_ref),
  FOREIGN KEY (tenant_id, batch_id) REFERENCES import_batch);
CREATE INDEX activity_vendor ON activity (tenant_id, vendor_ref) WHERE kind = 'ap';
SELECT enable_tenant_rls('activity');

CREATE TABLE factor_version (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id text NOT NULL,                                  -- 'EF-2025.1'
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'frozen')),
  based_on text,
  notes text,
  content_hash text,                                 -- SHA-256 of every factor in it, set when frozen
  created_by uuid,
  frozen_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('factor_version');

CREATE TABLE emission_factor (
  tenant_id uuid NOT NULL REFERENCES tenants,
  version text NOT NULL,
  id text NOT NULL,                                  -- SPEND:steel_metals:EU, GRID:DE, FREIGHT:air, SUP:<supplier>
  kind text NOT NULL CHECK (kind IN ('spend', 'electricity', 'fuel', 'freight', 'supplier')),
  category text NOT NULL,
  geography text NOT NULL,
  year int NOT NULL,
  unit text NOT NULL,
  value double precision NOT NULL CHECK (value >= 0),
  gsd double precision NOT NULL CHECK (gsd >= 1),    -- geometric standard deviation of the factor itself
  dispersion double precision NOT NULL DEFAULT 0,    -- (+) log-sd of one supplier around a sector mean (spend factors)
  source text NOT NULL,
  supplier_id uuid,                                  -- supplier-specific factors
  evidence_id uuid,                                  -- the disclosure it came from
  PRIMARY KEY (tenant_id, version, id),
  FOREIGN KEY (tenant_id, version) REFERENCES factor_version);
SELECT enable_tenant_rls('emission_factor');

-- A frozen version can never change: no factor added, edited or removed, and it cannot be unfrozen.
CREATE FUNCTION factor_frozen_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v text; t uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN v := OLD.version; t := OLD.tenant_id; ELSE v := NEW.version; t := NEW.tenant_id; END IF;
  IF EXISTS (SELECT 1 FROM factor_version WHERE tenant_id = t AND id = v AND status = 'frozen')
     OR (TG_OP = 'UPDATE' AND EXISTS (SELECT 1 FROM factor_version WHERE tenant_id = OLD.tenant_id AND id = OLD.version AND status = 'frozen')) THEN
    RAISE EXCEPTION 'factor version % is frozen', v;
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER factor_frozen BEFORE INSERT OR UPDATE OR DELETE ON emission_factor FOR EACH ROW EXECUTE FUNCTION factor_frozen_guard();

CREATE FUNCTION version_frozen_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'frozen' THEN RAISE EXCEPTION 'factor version % is frozen', OLD.id; END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER version_frozen BEFORE UPDATE OR DELETE ON factor_version FOR EACH ROW EXECUTE FUNCTION version_frozen_guard();

CREATE TABLE calculation (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id uuid NOT NULL,
  factor_version text NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  lines int NOT NULL,
  totals jsonb NOT NULL,                             -- by scope, category, method, subsidiary, supplier; uncertainty
  result_hash text NOT NULL,                         -- SHA-256 over every line's activity, factor and CO2e
  inputs_hash text NOT NULL,                         -- (+) over the activities, mappings and suppliers it read
  lineage_coverage double precision NOT NULL,
  model_versions jsonb NOT NULL,
  created_by uuid NOT NULL,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, factor_version) REFERENCES factor_version);
SELECT enable_tenant_rls('calculation');

-- One row per activity per calculation: the CO2e figure and every link it was made from.
CREATE TABLE calculation_lineage (
  tenant_id uuid NOT NULL REFERENCES tenants,
  calculation_id uuid NOT NULL,
  activity_id bigint NOT NULL REFERENCES activity,
  supplier_key text,                                 -- the resolved supplier, or the vendor record when unresolved
  scope smallint NOT NULL,
  category text,
  method text NOT NULL,                              -- spend-based, supplier-specific, activity, covered, unmapped
  factor_id text,
  co2e_kg double precision NOT NULL,
  PRIMARY KEY (calculation_id, activity_id),
  FOREIGN KEY (tenant_id, calculation_id) REFERENCES calculation);
SELECT enable_tenant_rls('calculation_lineage');

CREATE TABLE scenario (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id uuid NOT NULL,
  calculation_id uuid NOT NULL,
  name text NOT NULL,
  request jsonb NOT NULL,
  result jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, calculation_id) REFERENCES calculation);
SELECT enable_tenant_rls('scenario');

-- What an assurer asks for: the disclosures as received with what was read from them, reproduction checks, exports.
CREATE TABLE assurance_evidence (
  tenant_id uuid NOT NULL REFERENCES tenants,
  id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('disclosure', 'reproduction', 'export')),
  subject text NOT NULL,
  supplier_id uuid,
  content text NOT NULL,
  sha256 text NOT NULL,
  extracted jsonb,
  status text NOT NULL DEFAULT 'received',           -- disclosures: received, accepted, review
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('assurance_evidence');

CREATE TABLE decision_record (                       -- a high-impact action proposed, then approved or rejected by someone else
  tenant_id uuid NOT NULL REFERENCES tenants,
  id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('publish_inventory', 'adopt_factor_version')),
  subject text NOT NULL,
  rationale jsonb NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected')),
  proposed_by uuid NOT NULL,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
SELECT enable_tenant_rls('decision_record');

CREATE TABLE review_task (                           -- (+) the operations inbox: what a person has to look at
  tenant_id uuid NOT NULL REFERENCES tenants,
  id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('category', 'supplier_match', 'disclosure')),
  subject text NOT NULL,
  detail jsonb NOT NULL,
  weight double precision NOT NULL DEFAULT 0,        -- spend or emissions at stake, for ordering
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id));
CREATE INDEX review_open ON review_task (tenant_id, kind, weight DESC) WHERE status = 'open';
SELECT enable_tenant_rls('review_task');

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

-- Every inference: model version and a hash of its inputs, never the raw inputs. Distinct inputs are logged once with a count.
CREATE TABLE model_runs (
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  model_name text NOT NULL,
  version text NOT NULL,
  subject text NOT NULL,
  inputs_hash text NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX model_runs_hash ON model_runs (tenant_id, inputs_hash);
SELECT enable_tenant_rls('model_runs');
