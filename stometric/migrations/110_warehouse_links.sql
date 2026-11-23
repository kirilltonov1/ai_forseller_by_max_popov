-- Explicit source-shop links, scoped to an owner workspace. No changes to marketplace data.
CREATE TABLE IF NOT EXISTS warehouse_links (
 workspace_id int NOT NULL REFERENCES workspaces(id),
 source_shop_id int NOT NULL,
 account_id int NOT NULL REFERENCES accounts(id),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (workspace_id,source_shop_id),
 UNIQUE (workspace_id,account_id)
);
