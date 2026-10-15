-- People records, editing (#435): what members write about a person, and the value a member's
-- correction replaced, so "Use Tin's score" can bring Tin's score back.

-- Notes a member wrote about a person. Only their author edits one; Forget deletes them.
CREATE TABLE IF NOT EXISTS record_notes (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    record_id uuid NOT NULL,
    body text NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
    author text NOT NULL CHECK (length(author) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (project_id, record_id) REFERENCES records (project_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS record_notes_record ON record_notes (record_id, created_at DESC);

-- The run's value a member's value replaced: {text, number, reason, set_by, definition, set_at}.
ALTER TABLE record_values ADD COLUMN IF NOT EXISTS previous jsonb
    CHECK (previous IS NULL OR jsonb_typeof(previous) = 'object');
