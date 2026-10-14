-- People records, first slice (#435): one lasting record per person a project knows, how each
-- is recognized across sources, typed fields whose every value says who set it, when and why,
-- and an append-only timeline. Segments, the commit log and agent copies come later.
CREATE TABLE IF NOT EXISTS records (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    type text NOT NULL CHECK (type IN ('person')),
    -- A record merged into another points at it; its events stay where they were written.
    merged_into uuid REFERENCES records(id),
    -- Where the record came from first, such as a workflow key, and that run.
    source text NOT NULL CHECK (length(source) BETWEEN 1 AND 100),
    source_run_id uuid REFERENCES workflow_runs(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, id)
);
CREATE INDEX IF NOT EXISTS records_current ON records (project_id, type, created_at DESC)
    WHERE merged_into IS NULL;

-- How a record is recognized: a LinkedIn member ID (the ACo… profile ID) or profile slug.
CREATE TABLE IF NOT EXISTS record_identifiers (
    project_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('linkedin_member', 'linkedin_slug')),
    value text NOT NULL CHECK (length(value) BETWEEN 1 AND 300),
    record_id uuid NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, kind, value),
    FOREIGN KEY (project_id, record_id) REFERENCES records (project_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS record_identifiers_record ON record_identifiers (record_id);

-- Field definitions, so a new field needs no migration.
CREATE TABLE IF NOT EXISTS record_fields (
    project_id uuid NOT NULL REFERENCES projects(id),
    key text NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{0,62}$'),
    type text NOT NULL CHECK (type IN ('text', 'number', 'choice')),
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 100),
    options jsonb CHECK (options IS NULL OR jsonb_typeof(options) = 'array'),
    built_in boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, key)
);

-- One current value per record and field. An empty value can still say why it is empty.
CREATE TABLE IF NOT EXISTS record_values (
    project_id uuid NOT NULL,
    record_id uuid NOT NULL,
    field text NOT NULL,
    value_text text CHECK (length(value_text) <= 2000),
    value_number double precision,
    reason text NOT NULL DEFAULT '' CHECK (length(reason) <= 500),
    -- A run or a member. A value a member set is never replaced by a run.
    set_by_kind text NOT NULL CHECK (set_by_kind IN ('run', 'member')),
    set_by text NOT NULL CHECK (length(set_by) BETWEEN 1 AND 200),
    -- What it was computed under, such as the ICP file's revision, so a changed definition
    -- shows old values as stale.
    definition text NOT NULL DEFAULT '' CHECK (length(definition) <= 200),
    set_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (record_id, field),
    FOREIGN KEY (project_id, record_id) REFERENCES records (project_id, id) ON DELETE CASCADE,
    FOREIGN KEY (project_id, field) REFERENCES record_fields (project_id, key)
);
CREATE INDEX IF NOT EXISTS record_values_number ON record_values (project_id, field, value_number)
    WHERE value_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS record_values_text ON record_values (project_id, field, value_text)
    WHERE value_text IS NOT NULL;

-- The timeline. Rows are only added; event_key makes a repeated read add nothing.
CREATE TABLE IF NOT EXISTS record_events (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    record_id uuid NOT NULL,
    kind text NOT NULL
        CHECK (kind IN ('reacted', 'commented', 'invited', 'accepted', 'withdrawn')),
    event_key text NOT NULL CHECK (length(event_key) BETWEEN 1 AND 300),
    occurred_at timestamptz,
    detail jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(detail) = 'object'),
    run_id uuid REFERENCES workflow_runs(id),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, event_key),
    FOREIGN KEY (project_id, record_id) REFERENCES records (project_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS record_events_record ON record_events (record_id, recorded_at DESC);

-- People the founder asked Tin to forget: a hash of each identifier, never the identifier.
CREATE TABLE IF NOT EXISTS record_suppressions (
    project_id uuid NOT NULL REFERENCES projects(id),
    identifier_hash text NOT NULL CHECK (identifier_hash ~ '^[0-9a-f]{64}$'),
    forgotten_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, identifier_hash)
);
