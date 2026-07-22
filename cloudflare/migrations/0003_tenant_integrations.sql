CREATE TABLE IF NOT EXISTS tenant_integrations (
  tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  whatsapp_enabled INTEGER NOT NULL DEFAULT 0 CHECK (whatsapp_enabled IN (0, 1)),
  meta_phone_number_id TEXT NOT NULL DEFAULT '',
  meta_waba_id TEXT NOT NULL DEFAULT '',
  meta_graph_version TEXT NOT NULL DEFAULT 'v25.0',
  meta_access_token_encrypted TEXT NOT NULL DEFAULT '',
  meta_app_secret_encrypted TEXT NOT NULL DEFAULT '',
  meta_verify_token_encrypted TEXT NOT NULL DEFAULT '',
  whatsapp_status TEXT NOT NULL DEFAULT 'pending',
  whatsapp_checked_at TEXT,
  ai_provider TEXT NOT NULL DEFAULT 'workers-ai',
  ai_model TEXT NOT NULL DEFAULT '@cf/zai-org/glm-4.7-flash',
  ai_api_key_encrypted TEXT NOT NULL DEFAULT '',
  ai_status TEXT NOT NULL DEFAULT 'pending',
  ai_checked_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_tenant_integrations_updated
  ON tenant_integrations(updated_at);
