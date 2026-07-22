CREATE TABLE IF NOT EXISTS tenant_settings (
  tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  bot_name TEXT NOT NULL DEFAULT 'Asistente',
  tone TEXT NOT NULL DEFAULT 'Profesional y cercano',
  welcome_message TEXT NOT NULL DEFAULT 'Hola, ¿cómo puedo ayudarte?',
  system_instructions TEXT NOT NULL DEFAULT '',
  ai_provider TEXT NOT NULL DEFAULT 'workers-ai',
  ai_model TEXT NOT NULL DEFAULT '@cf/qwen/qwen3-embedding-0.6b',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE auth_sessions ADD COLUMN csrf_token TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS ix_tenant_settings_updated
  ON tenant_settings(updated_at);
