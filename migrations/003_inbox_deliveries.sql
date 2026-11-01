-- Message-inbox items already delivered, so an item the service offers again is acknowledged, not sent twice.
CREATE TABLE inbox_deliveries (
  item_id      text PRIMARY KEY,
  external_ref text NOT NULL,
  delivered_at timestamptz NOT NULL DEFAULT now()
);
