BEGIN;

ALTER TABLE positions ADD COLUMN position_idx INTEGER NOT NULL DEFAULT 0;
ALTER TABLE positions DROP CONSTRAINT positions_pkey;
ALTER TABLE positions ADD CONSTRAINT positions_pkey
    PRIMARY KEY (venue, environment, product_type, symbol, position_idx);
ALTER TABLE positions ADD CONSTRAINT positions_position_idx_check
    CHECK (position_idx IN (0, 1, 2));

COMMIT;
