-- Drift Metrics: Longitudinal metrics computed nightly from turn_metrics
-- Tracks how the system's behavior changes over time (embedding centroids,
-- emotional baselines, vocabulary entropy, etc.)

CREATE TABLE IF NOT EXISTS drift_metrics (
    id BIGSERIAL PRIMARY KEY,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value FLOAT4,
    metric_vector VECTOR(768),
    metric_json JSONB,
    sample_count INT
);

CREATE INDEX IF NOT EXISTS idx_drift_metrics_name ON drift_metrics(metric_name, computed_at);
