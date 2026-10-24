PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    experiment_name TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    feedback_condition TEXT NOT NULL,
    split TEXT NOT NULL,
    seed INTEGER NOT NULL,
    contract_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_revisions INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    python_version TEXT NOT NULL,
    platform TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    revision_index INTEGER NOT NULL,
    call_index INTEGER NOT NULL,
    selected INTEGER NOT NULL,
    parameters_json TEXT NOT NULL,
    raw_response TEXT NOT NULL,
    usage_json TEXT NOT NULL DEFAULT '{}',
    valid INTEGER NOT NULL,
    validation_error TEXT,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    latency_seconds REAL NOT NULL,
    estimated_cost_usd REAL NOT NULL,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (experiment_id, revision_index, call_index)
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    revision_index INTEGER NOT NULL,
    episode_index INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    total_reward REAL,
    success INTEGER,
    crashed INTEGER,
    steps INTEGER NOT NULL,
    terminated INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    elapsed_seconds REAL NOT NULL,
    metrics_json TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (experiment_id, revision_index, episode_index)
);

CREATE TABLE IF NOT EXISTS errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    phase TEXT NOT NULL,
    message TEXT NOT NULL,
    revision_index INTEGER,
    episode_index INTEGER,
    traceback TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    experiment_id TEXT PRIMARY KEY REFERENCES experiments(experiment_id),
    next_revision_index INTEGER NOT NULL,
    budget_json TEXT NOT NULL,
    seed_schedule_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_experiment
    ON attempts (experiment_id, revision_index, call_index);

CREATE INDEX IF NOT EXISTS idx_episodes_experiment
    ON episodes (experiment_id, revision_index, episode_index);

CREATE INDEX IF NOT EXISTS idx_errors_experiment
    ON errors (experiment_id);

CREATE INDEX IF NOT EXISTS idx_sessions_experiment
    ON sessions (experiment_id);

CREATE VIEW IF NOT EXISTS scores AS
SELECT
    episode_id,
    experiment_id,
    session_id,
    revision_index,
    episode_index,
    seed,
    total_reward AS score,
    success,
    crashed,
    steps,
    elapsed_seconds,
    metrics_json,
    error,
    created_at
FROM episodes;

-- Held-out freeze / evaluation (additive; schema_version stays 1).
-- These tables are never read into ModelRequest history.
CREATE TABLE IF NOT EXISTS frozen_controllers (
    freeze_id TEXT PRIMARY KEY,
    controller_hash TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    source_experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    source_attempt_id INTEGER NOT NULL,
    source_revision_index INTEGER NOT NULL,
    source_call_index INTEGER NOT NULL,
    source_session_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    feedback_condition TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    selection_rule TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source_experiment_id, selection_rule, controller_hash)
);

CREATE TABLE IF NOT EXISTS heldout_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    freeze_id TEXT NOT NULL REFERENCES frozen_controllers(freeze_id),
    source_experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    environment_id TEXT NOT NULL,
    environment_version TEXT NOT NULL,
    start_schedule_version TEXT NOT NULL,
    vary_fuel INTEGER NOT NULL,
    held_out_seeds_json TEXT NOT NULL,
    max_episode_steps INTEGER,
    status TEXT NOT NULL,
    controller_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_episodes INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    UNIQUE (freeze_id, held_out_seeds_json, start_schedule_version, environment_version, vary_fuel, max_episode_steps)
);

CREATE TABLE IF NOT EXISTS heldout_episodes (
    heldout_episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id TEXT NOT NULL REFERENCES heldout_evaluations(evaluation_id),
    freeze_id TEXT NOT NULL REFERENCES frozen_controllers(freeze_id),
    source_experiment_id TEXT NOT NULL,
    episode_index INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    total_reward REAL,
    success INTEGER,
    crashed INTEGER,
    steps INTEGER NOT NULL,
    terminated INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    elapsed_seconds REAL NOT NULL,
    metrics_json TEXT NOT NULL,
    initial_state_json TEXT NOT NULL,
    replay_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (evaluation_id, episode_index),
    UNIQUE (evaluation_id, seed)
);

CREATE INDEX IF NOT EXISTS idx_frozen_controllers_source
    ON frozen_controllers (source_experiment_id);

CREATE INDEX IF NOT EXISTS idx_heldout_evaluations_source
    ON heldout_evaluations (source_experiment_id, freeze_id);

CREATE INDEX IF NOT EXISTS idx_heldout_episodes_evaluation
    ON heldout_episodes (evaluation_id, episode_index);
