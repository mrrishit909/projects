-- Knowledge-graph domain. Follows the blueprint's tables (source_system, source_object, principal, entity, entity_alias,
-- relationship, evidence, permission_edge, embedding, temporal_fact, query_audit); additions are marked (+). Raw bodies sit
-- on source_object here (object storage in production). Every table is tenant-scoped with row-level security; which rows
-- a *person* may read inside a tenant is the permission engine's job (containers and groups), enforced before ranking.

CREATE TABLE corpora (                               -- (+) the simulated enterprise behind the six source systems
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  name text NOT NULL,
  model_seed bigint NOT NULL,                        -- the generator's seed
  clock int NOT NULL,                                -- simulated today, in days from 2025-08-04
  told jsonb NOT NULL DEFAULT '[]',                  -- events the generator was told about (simulation truth, never read by the pipeline)
  index_version int NOT NULL DEFAULT 0,              -- bumped by every sync and merge; caches key on it
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id));
SELECT enable_tenant_rls('corpora');

CREATE TABLE source_system (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  external_ref text NOT NULL,                        -- hr, code, wiki, tickets, crm, chat
  name text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',              -- cursor (last synced day), last sync, containers
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_ref));
SELECT enable_tenant_rls('source_system');

CREATE TABLE source_object (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  source_system_id uuid NOT NULL REFERENCES source_system,
  external_id text NOT NULL,
  container text NOT NULL,                           -- (+) space, project, channel or record type: what the ACL is on
  kind text NOT NULL,
  title text NOT NULL,
  author text,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
  attributes jsonb NOT NULL DEFAULT '{}',
  body text NOT NULL,                                -- (+) the normalised text; object storage in production
  content_hash text NOT NULL,
  version int NOT NULL DEFAULT 1,
  observed_day int NOT NULL,                         -- when the source last changed it (simulated days)
  observed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  synced_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, source_system_id, external_id));
CREATE INDEX source_object_container ON source_object (tenant_id, container);
SELECT enable_tenant_rls('source_object');

CREATE TABLE principal (                             -- users and groups as the identity source reports them
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  kind text NOT NULL CHECK (kind IN ('user', 'group')),
  external_ref text NOT NULL,                        -- email or group name
  display_name text NOT NULL,
  actor_id uuid,                                     -- (+) the API identity this user signs in as
  UNIQUE (tenant_id, external_ref));
CREATE INDEX principal_actor ON principal (tenant_id, actor_id);
SELECT enable_tenant_rls('principal');

CREATE TABLE permission_edge (                       -- user member_of group; group (or user) can_read container
  tenant_id uuid NOT NULL REFERENCES tenants,
  principal_id uuid NOT NULL REFERENCES principal ON DELETE CASCADE,
  relation text NOT NULL CHECK (relation IN ('member_of', 'can_read')),
  target text NOT NULL,
  source_system_id uuid REFERENCES source_system,
  synced_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, principal_id, relation, target));
SELECT enable_tenant_rls('permission_edge');

CREATE TABLE document_chunk (                        -- (+) what the document normalizer cuts a body into
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  source_object_id uuid NOT NULL REFERENCES source_object ON DELETE CASCADE,
  ord int NOT NULL,
  start_offset int NOT NULL,
  end_offset int NOT NULL,
  text text NOT NULL);
CREATE INDEX chunk_object ON document_chunk (source_object_id);
SELECT enable_tenant_rls('document_chunk');

CREATE TABLE entity (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  type text NOT NULL CHECK (type IN ('person', 'team', 'service', 'vendor', 'decision', 'incident')),
  canonical_key text NOT NULL,                       -- anchor key (HR email, org slug, service slug, CRM account) or a NIL key
  canonical_name text NOT NULL,
  anchored boolean NOT NULL,                         -- (+) backed by a structured record
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged')),
  merged_into uuid REFERENCES entity,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, canonical_key));
SELECT enable_tenant_rls('entity');

CREATE TABLE entity_alias (                          -- every surface form seen for an entity, tenant-wide (what a steward sees)
  tenant_id uuid NOT NULL REFERENCES tenants,
  entity_id uuid NOT NULL REFERENCES entity,
  alias text NOT NULL,
  mentions int NOT NULL,
  PRIMARY KEY (tenant_id, entity_id, alias));
SELECT enable_tenant_rls('entity_alias');

CREATE TABLE mention (                               -- (+) one entity mention in a chunk, and what it was resolved to
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  chunk_id uuid NOT NULL REFERENCES document_chunk ON DELETE CASCADE,
  source_object_id uuid NOT NULL REFERENCES source_object ON DELETE CASCADE,
  start_offset int NOT NULL,
  end_offset int NOT NULL,
  text text NOT NULL,
  type text NOT NULL,
  entity_id uuid REFERENCES entity,                  -- NULL: the linker abstained (two candidates scored alike)
  score double precision NOT NULL,
  method text NOT NULL,
  linker_version text NOT NULL);
CREATE INDEX mention_entity ON mention (tenant_id, entity_id);
CREATE INDEX mention_chunk ON mention (chunk_id);
SELECT enable_tenant_rls('mention');

CREATE TABLE relationship (                          -- one assertion read from one sentence (an edge before reconciliation)
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  chunk_id uuid NOT NULL REFERENCES document_chunk ON DELETE CASCADE,
  source_object_id uuid NOT NULL REFERENCES source_object ON DELETE CASCADE,
  predicate text NOT NULL,
  subject_id uuid NOT NULL REFERENCES entity,
  object_id uuid REFERENCES entity,
  value text,                                        -- a literal: a reason, a price
  from_id uuid REFERENCES entity,                    -- a handover's previous owner
  effective_day int,                                 -- a stated effective date
  asserted_day int NOT NULL,                         -- the source's date for the statement
  sentence int[] NOT NULL,                           -- [start, end) in the body
  confidence double precision NOT NULL,
  method text NOT NULL,                              -- structured, model, pattern
  source_kind text NOT NULL,
  subject_mention uuid,
  object_mention uuid,
  extractor_version text NOT NULL);
CREATE INDEX relationship_subject ON relationship (tenant_id, subject_id);
CREATE INDEX relationship_object ON relationship (tenant_id, object_id);
SELECT enable_tenant_rls('relationship');

CREATE TABLE temporal_fact (                         -- reconciled facts over every container (the steward's published view);
  id uuid PRIMARY KEY,                               -- each reader's facts are re-derived from the assertions they may read
  tenant_id uuid NOT NULL REFERENCES tenants,
  subject_id uuid NOT NULL REFERENCES entity,
  predicate text NOT NULL,
  object_id uuid REFERENCES entity,
  value text,
  valid_from date,
  valid_to date,                                     -- exclusive; NULL = still true
  confidence double precision NOT NULL,
  method text NOT NULL,
  index_version int NOT NULL);
CREATE INDEX temporal_subject ON temporal_fact (tenant_id, subject_id);
CREATE INDEX temporal_object ON temporal_fact (tenant_id, object_id);
SELECT enable_tenant_rls('temporal_fact');

CREATE TABLE evidence (
  tenant_id uuid NOT NULL REFERENCES tenants,
  fact_id uuid NOT NULL REFERENCES temporal_fact ON DELETE CASCADE,
  relationship_id uuid NOT NULL REFERENCES relationship ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('supports', 'contradicts')),
  PRIMARY KEY (fact_id, relationship_id));
SELECT enable_tenant_rls('evidence');

CREATE TABLE embedding (                             -- LSA vectors, per permission view (a view's basis is fitted on what it may read)
  tenant_id uuid NOT NULL REFERENCES tenants,
  view_key text NOT NULL,
  index_version int NOT NULL,
  chunk_id uuid NOT NULL REFERENCES document_chunk ON DELETE CASCADE,
  model_version text NOT NULL,
  vector real[] NOT NULL,
  PRIMARY KEY (tenant_id, view_key, index_version, chunk_id));
SELECT enable_tenant_rls('embedding');

CREATE TABLE query_audit (                           -- who asked what (hashed), through which view, and which sources came back
  id bigserial PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  principal_id uuid REFERENCES principal,
  actor_id uuid NOT NULL,
  endpoint text NOT NULL,
  query_sha256 text NOT NULL,
  intent text,
  view_key text NOT NULL,
  returned_objects uuid[] NOT NULL DEFAULT '{}',
  abstained boolean,
  model_versions jsonb NOT NULL DEFAULT '{}',
  latency_ms double precision NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX query_audit_time ON query_audit (tenant_id, created_at DESC);
SELECT enable_tenant_rls('query_audit');

CREATE TABLE merge_proposal (                        -- (+) decision_record for merging two entities: suggested by the system or a person,
  id uuid PRIMARY KEY,                               -- proposed by one person, approved by another
  tenant_id uuid NOT NULL REFERENCES tenants,
  keep_entity uuid NOT NULL REFERENCES entity,
  merge_entity uuid NOT NULL REFERENCES entity,
  reason jsonb NOT NULL,
  status text NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested', 'proposed', 'approved', 'rejected')),
  proposed_by uuid,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, keep_entity, merge_entity));
SELECT enable_tenant_rls('merge_proposal');

CREATE TABLE sync_runs (                             -- (+) every connector sync: what changed and how long until it was queryable
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants,
  mode text NOT NULL CHECK (mode IN ('full', 'incremental')),
  from_day int,
  to_day int NOT NULL,
  stats jsonb NOT NULL,
  requested_at timestamptz NOT NULL,
  finished_at timestamptz NOT NULL,
  pipeline_seconds double precision NOT NULL,
  index_version int NOT NULL);
SELECT enable_tenant_rls('sync_runs');

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

-- Every inference batch: model version and a hash of its inputs, never the raw inputs.
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
