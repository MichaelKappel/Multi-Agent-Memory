-- MemoryEndpoints.com MATM database schema proposal.
-- This file is safe to publish: it contains no credentials.
-- The stdlib SQLite backend is live separately. MySQL/MariaDB production
-- activation is gated because the runtime currently has no approved
-- no-third-party MySQL adapter.

CREATE TABLE matm_workspaces (
  workspace_id VARCHAR(96) PRIMARY KEY,
  label VARCHAR(255) NOT NULL,
  plan VARCHAR(64) NOT NULL,
  storage_limit_bytes BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE matm_api_keys (
  key_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  token_hash CHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_api_keys_hash (token_hash),
  KEY ix_matm_api_keys_workspace (workspace_id)
);

CREATE TABLE matm_agents (
  workspace_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL,
  registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (workspace_id, agent_id)
);

CREATE TABLE matm_memory_events (
  event_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  actor_agent_id VARCHAR(128) NOT NULL,
  scope VARCHAR(64) NOT NULL,
  title VARCHAR(255) NOT NULL,
  summary TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  source VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_memory_workspace_created (workspace_id, created_at),
  FULLTEXT KEY fx_matm_memory_summary (title, summary)
);

CREATE TABLE matm_messages (
  message_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  sender_agent_id VARCHAR(128) NOT NULL,
  target_agent_id VARCHAR(128) NULL,
  safe_summary TEXT NOT NULL,
  response_required TINYINT(1) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_messages_workspace_created (workspace_id, created_at)
);

CREATE TABLE matm_notifications (
  notification_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  message_id VARCHAR(96) NOT NULL,
  target_agent_id VARCHAR(128) NULL,
  status VARCHAR(32) NOT NULL,
  response_disposition VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at TIMESTAMP NULL,
  KEY ix_matm_notifications_target_status (workspace_id, target_agent_id, status)
);

CREATE TABLE matm_receipts (
  receipt_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  notification_id VARCHAR(96) NOT NULL,
  consumer_agent_id VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_receipts_notification (notification_id)
);

CREATE TABLE matm_idempotency (
  record_key VARCHAR(255) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  operation VARCHAR(96) NOT NULL,
  body_hash CHAR(64) NOT NULL,
  response_json MEDIUMTEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_idempotency_workspace (workspace_id)
);

CREATE TABLE matm_audit_log (
  audit_id VARCHAR(96) PRIMARY KEY,
  action VARCHAR(128) NOT NULL,
  actor VARCHAR(128) NULL,
  target VARCHAR(128) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1
);
