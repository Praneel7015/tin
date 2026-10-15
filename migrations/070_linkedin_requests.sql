-- Connection requests a member approves, sent one at a time from their saved LinkedIn session
-- (#450). Pacing is per member across projects; every request keeps what became of it.

-- A member's sending on one project: off until they tick the consent box on the LinkedIn card.
CREATE TABLE IF NOT EXISTS linkedin_sending (
    project_id uuid NOT NULL REFERENCES projects(id),
    member text NOT NULL CHECK (length(member) BETWEEN 1 AND 200),
    enabled boolean NOT NULL DEFAULT false,
    consent_version integer,
    consented_at timestamptz,
    daily_cap integer NOT NULL DEFAULT 15 CHECK (daily_cap BETWEEN 1 AND 25),
    weekly_cap integer NOT NULL DEFAULT 60 CHECK (weekly_cap BETWEEN 1 AND 100),
    -- Minutes after local midnight, weekdays only, in the project's time zone.
    start_minute integer NOT NULL DEFAULT 540 CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute integer NOT NULL DEFAULT 1020 CHECK (end_minute BETWEEN 1 AND 1440),
    -- Why sending stopped (LinkedIn's warning, a signed-out session) until the member resumes,
    -- or until when LinkedIn's limit holds it.
    paused_reason text CHECK (paused_reason IS NULL OR length(paused_reason) <= 60),
    paused_at timestamptz,
    paused_until timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, member),
    CHECK (start_minute < end_minute)
);

-- People proposed together, waiting in Decisions for the member whose LinkedIn would send.
CREATE TABLE IF NOT EXISTS linkedin_request_batches (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    member text NOT NULL CHECK (length(member) BETWEEN 1 AND 200),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'approved', 'discarded')),
    source_run_id uuid REFERENCES workflow_runs(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    decision_request_id uuid UNIQUE,
    send_run_id uuid REFERENCES workflow_runs(id),
    checked_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS linkedin_request_batches_open
    ON linkedin_request_batches (project_id, member) WHERE status = 'open';

-- One person in one batch, and what became of the request.
CREATE TABLE IF NOT EXISTS linkedin_requests (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    batch_id uuid NOT NULL REFERENCES linkedin_request_batches(id) ON DELETE CASCADE,
    record_id uuid NOT NULL,
    member text NOT NULL CHECK (length(member) BETWEEN 1 AND 200),
    -- The person's LinkedIn profile ID (ACo…), as the request names them.
    target text NOT NULL CHECK (target ~ '^ACo[A-Za-z0-9_-]{20,80}$'),
    status text NOT NULL DEFAULT 'proposed' CHECK (status IN (
        'proposed', 'declined', 'queued', 'sending', 'sent', 'accepted', 'not_pending',
        'connected', 'invited', 'unknown_person', 'refused', 'uncertain', 'not_sent',
        'lapsed')),
    queued_at timestamptz,
    attempted_at timestamptz,
    sent_at timestamptz,
    settled_at timestamptz,
    invitation text CHECK (invitation IS NULL OR length(invitation) <= 120),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (batch_id, record_id),
    FOREIGN KEY (project_id, record_id) REFERENCES records (project_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS linkedin_requests_member_attempts
    ON linkedin_requests (member, attempted_at) WHERE attempted_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS linkedin_requests_record ON linkedin_requests (project_id, record_id);
