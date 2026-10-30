BEGIN;

CREATE TABLE account_snapshots (
    snapshot_id VARCHAR(128) PRIMARY KEY,
    venue VARCHAR(32) NOT NULL,
    environment VARCHAR(32) NOT NULL,
    snapshot JSONB NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_account_snapshots_scope_time
    ON account_snapshots(venue, environment, as_of DESC);

CREATE TABLE account_balances (
    venue VARCHAR(32) NOT NULL,
    environment VARCHAR(32) NOT NULL,
    asset VARCHAR(32) NOT NULL,
    total NUMERIC(38, 18) NOT NULL CHECK (total >= 0),
    available NUMERIC(38, 18) NOT NULL CHECK (available >= 0 AND available <= total),
    as_of TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (venue, environment, asset)
);

CREATE TABLE positions (
    venue VARCHAR(32) NOT NULL,
    environment VARCHAR(32) NOT NULL,
    product_type VARCHAR(32) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    position_idx INTEGER NOT NULL DEFAULT 0 CHECK (position_idx IN (0, 1, 2)),
    settlement_asset VARCHAR(32) NOT NULL,
    signed_quantity NUMERIC(38, 18) NOT NULL,
    average_entry_price NUMERIC(38, 18) NOT NULL CHECK (average_entry_price >= 0),
    mark_price NUMERIC(38, 18) NOT NULL CHECK (mark_price > 0),
    unrealized_pnl NUMERIC(38, 18) NOT NULL,
    leverage NUMERIC(38, 18) NOT NULL CHECK (leverage > 0),
    liquidation_price NUMERIC(38, 18) CHECK (liquidation_price > 0),
    as_of TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (venue, environment, product_type, symbol, position_idx)
);

COMMIT;
