-- uneXpected v8 additive migration: governed media-job state only.
-- Large project and rendered media bytes remain in a separately configured artifact root.
BEGIN;

CREATE TABLE IF NOT EXISTS media_jobs (
    job_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    request_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'claimed', 'inspecting', 'rendering', 'post_render_qa',
        'ready_for_human_review', 'failed', 'qa_blocked',
        'cancel_requested', 'cancelled'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at DOUBLE PRECISION,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    result_json TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    UNIQUE (task_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_media_jobs_state_created
    ON media_jobs(state, created_at, job_id);
CREATE INDEX IF NOT EXISTS idx_media_jobs_lease
    ON media_jobs(state, lease_expires_at);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (3, '003_openfilm_media_jobs.sql', EXTRACT(EPOCH FROM clock_timestamp()))
ON CONFLICT(version) DO NOTHING;

COMMIT;
