BEGIN;

CREATE TABLE balance_reservations (
    reservation_id VARCHAR(128) PRIMARY KEY,
    client_order_id VARCHAR(64) NOT NULL UNIQUE
        REFERENCES orders(client_order_id) ON DELETE RESTRICT,
    venue VARCHAR(32) NOT NULL,
    environment VARCHAR(32) NOT NULL,
    asset VARCHAR(32) NOT NULL,
    amount NUMERIC(38, 18) NOT NULL CHECK (amount > 0),
    status VARCHAR(16) NOT NULL CHECK (status IN ('active', 'released')),
    created_at TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ
);
CREATE INDEX ix_active_balance_reservations
    ON balance_reservations(venue, environment, asset)
    WHERE status = 'active';

COMMIT;
