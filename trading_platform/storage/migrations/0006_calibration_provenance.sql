BEGIN;

CREATE TABLE calibration_provenance (
    calibration_id VARCHAR(128) PRIMARY KEY,
    model_version VARCHAR(128) NOT NULL,
    manifest JSONB NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_calibration_provenance_model
    ON calibration_provenance(model_version, registered_at DESC);

COMMIT;
