CREATE TABLE observer_measurement_receipts(
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    receipt_schema TEXT NOT NULL,
    derivation_version TEXT NOT NULL,
    recommendation_status TEXT NOT NULL,
    packet_quality_status TEXT NOT NULL,
    attribution_status TEXT NOT NULL,
    measurement_status TEXT NOT NULL,
    legacy_unsafe INTEGER,
    legacy_superseded INTEGER NOT NULL CHECK(legacy_superseded IN (0, 1)),
    source_hash TEXT,
    receipt_json TEXT NOT NULL
);
CREATE INDEX observer_measurement_status_idx ON observer_measurement_receipts(measurement_status, recommendation_status);
