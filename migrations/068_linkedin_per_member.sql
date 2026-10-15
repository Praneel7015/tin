-- Every member of a project keeps their own LinkedIn reading connection (Tin for Chrome),
-- matched by who connected it, so one member pairing never replaces another's. Every other
-- integration stays one per project.
ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS integration_connections_project_id_provider_key_key;
CREATE UNIQUE INDEX IF NOT EXISTS integration_connections_one_per_project
    ON integration_connections (project_id, provider_key)
    WHERE provider_key <> 'network.linkedin';
CREATE UNIQUE INDEX IF NOT EXISTS integration_connections_linkedin_per_member
    ON integration_connections (project_id, provider_key, connected_by_clerk_user_id)
    WHERE provider_key = 'network.linkedin';
