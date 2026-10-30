BEGIN;

CREATE TABLE binary_settlements (
    venue_settlement_id VARCHAR(128) PRIMARY KEY,
    client_order_id VARCHAR(64) NOT NULL UNIQUE
        REFERENCES orders(client_order_id) ON DELETE RESTRICT,
    broker_order_id VARCHAR(128) NOT NULL,
    outcome VARCHAR(16) NOT NULL CHECK (outcome IN ('win', 'loss', 'tie', 'void')),
    stake NUMERIC(38, 18) NOT NULL CHECK (stake > 0),
    gross_return NUMERIC(38, 18) NOT NULL CHECK (gross_return >= 0),
    net_pnl NUMERIC(38, 18) NOT NULL,
    settlement_asset VARCHAR(32) NOT NULL,
    settled_at TIMESTAMPTZ NOT NULL,
    source VARCHAR(32) NOT NULL CHECK (source = 'broker_api'),
    evidence JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CHECK (net_pnl = gross_return - stake)
);
CREATE INDEX ix_binary_settlements_broker_order
    ON binary_settlements(broker_order_id, settled_at DESC);

COMMIT;
