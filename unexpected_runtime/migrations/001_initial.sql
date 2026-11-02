-- Version 1: durable core state for the unified uneXpected runtime.
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at);

CREATE TABLE IF NOT EXISTS events (
    event_id BIGSERIAL PRIMARY KEY,
    ts DOUBLE PRECISION NOT NULL,
    task_id TEXT,
    agent_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id);

CREATE TABLE IF NOT EXISTS agent_memory (
    agent_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (agent_id, key)
);

CREATE TABLE IF NOT EXISTS shared_knowledge (
    knowledge_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    trust_status TEXT NOT NULL,
    reviewed_by TEXT,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    idempotency_key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    success INTEGER NOT NULL,
    feedback TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    base_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    candidate_instruction TEXT NOT NULL,
    changes TEXT NOT NULL,
    protected_change INTEGER NOT NULL,
    benchmark_id TEXT NOT NULL,
    status TEXT NOT NULL,
    evaluation_json TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    protected_fields_json TEXT NOT NULL DEFAULT '[]',
    evaluation_context_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id TEXT NOT NULL,
    version TEXT NOT NULL,
    instruction TEXT NOT NULL,
    change_log TEXT NOT NULL,
    active SMALLINT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (agent_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_versions_one_active
    ON agent_versions(agent_id) WHERE active = 1;

CREATE TABLE IF NOT EXISTS baselines (
    agent_id TEXT NOT NULL,
    benchmark_id TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    active_version TEXT,
    instruction_sha256 TEXT,
    report_sha256 TEXT,
    PRIMARY KEY (agent_id, benchmark_id)
);

CREATE TABLE IF NOT EXISTS capabilities (
    capability_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capabilities_status_updated
    ON capabilities(status, updated_at);

CREATE TABLE IF NOT EXISTS consumed_approvals (
    approval_id TEXT PRIMARY KEY,
    action_digest TEXT NOT NULL,
    consumed_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_devices (
    device_id TEXT PRIMARY KEY,
    created_at DOUBLE PRECISION NOT NULL,
    last_seen_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_records (
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    source_device_id TEXT NOT NULL,
    source_updated_at TEXT,
    synced_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_records_type_synced
    ON workspace_records(record_type, synced_at);
