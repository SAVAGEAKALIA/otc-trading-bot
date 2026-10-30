BEGIN;

CREATE TABLE signal_decisions (
    signal_id UUID PRIMARY KEY,
    environment VARCHAR(32) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    product_type VARCHAR(32) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    proposal JSONB NOT NULL,
    risk_decision JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_signal_decisions_instrument_time
    ON signal_decisions(venue, product_type, symbol, created_at DESC);

COMMIT;
