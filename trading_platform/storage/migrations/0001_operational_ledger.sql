BEGIN;

CREATE TABLE orders (
    client_order_id VARCHAR(64) PRIMARY KEY,
    environment VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    broker_order_id VARCHAR(128),
    intent JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE order_events (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(160) NOT NULL UNIQUE,
    client_order_id VARCHAR(64) NOT NULL REFERENCES orders(client_order_id) ON DELETE RESTRICT,
    status VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_order_events_client_order_id ON order_events(client_order_id);

CREATE TABLE executions (
    id BIGSERIAL PRIMARY KEY,
    venue_execution_id VARCHAR(128) NOT NULL,
    client_order_id VARCHAR(64) NOT NULL REFERENCES orders(client_order_id) ON DELETE RESTRICT,
    quantity NUMERIC(38, 18) NOT NULL CHECK (quantity > 0),
    price NUMERIC(38, 18) NOT NULL CHECK (price > 0),
    fee NUMERIC(38, 18) NOT NULL CHECK (fee >= 0),
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_execution_venue_id UNIQUE (client_order_id, venue_execution_id)
);
CREATE INDEX ix_executions_client_order_id ON executions(client_order_id);

CREATE TABLE outbox (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(160) NOT NULL UNIQUE,
    topic VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    last_error TEXT
);
CREATE INDEX ix_outbox_pending ON outbox(id) WHERE published_at IS NULL;

COMMIT;
