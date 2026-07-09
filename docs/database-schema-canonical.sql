-- MemoryEndpoints.com canonical MATM database schema.
-- Safe to publish: contains no credentials, hosts, passwords, tokens, or keys.
-- Dialect target: MySQL/MariaDB with InnoDB and utf8mb4.
-- Runtime note: production requires this MySQL/MariaDB schema and a verified live connection.

CREATE TABLE IF NOT EXISTS matm_accounts (
  account_id VARCHAR(96) PRIMARY KEY,
  label VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS matm_companies (
  company_id VARCHAR(96) PRIMARY KEY,
  label VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_account_companies (
  membership_id VARCHAR(96) PRIMARY KEY,
  account_id VARCHAR(96) NOT NULL,
  company_id VARCHAR(96) NOT NULL,
  role VARCHAR(64) NOT NULL DEFAULT 'member',
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_account_company (account_id, company_id),
  KEY ix_matm_account_companies_account (account_id),
  KEY ix_matm_account_companies_company (company_id),
  CONSTRAINT fk_matm_account_companies_account FOREIGN KEY (account_id) REFERENCES matm_accounts (account_id),
  CONSTRAINT fk_matm_account_companies_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_workspaces (
  workspace_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  label VARCHAR(255) NOT NULL,
  plan VARCHAR(64) NOT NULL,
  storage_limit_bytes BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  KEY ix_matm_workspaces_company (company_id),
  CONSTRAINT fk_matm_workspaces_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_projects (
  project_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  label VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  KEY ix_matm_projects_workspace (workspace_id),
  CONSTRAINT fk_matm_projects_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_api_keys (
  key_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  token_hash CHAR(64) NOT NULL,
  label VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_api_keys_hash (token_hash),
  KEY ix_matm_api_keys_workspace (workspace_id),
  CONSTRAINT fk_matm_api_keys_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_agents (
  agent_record_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_agents_workspace_agent (workspace_id, agent_id),
  KEY ix_matm_agents_workspace (workspace_id),
  CONSTRAINT fk_matm_agents_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_memory_records (
  memory_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  actor_agent_id VARCHAR(128) NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NULL,
  memory_type VARCHAR(32) NOT NULL,
  subject VARCHAR(255) NULL,
  title VARCHAR(255) NOT NULL,
  public_safe_summary TEXT NOT NULL,
  source_uri VARCHAR(512) NULL,
  confidence DOUBLE NOT NULL,
  promotion_state VARCHAR(32) NOT NULL,
  review_status VARCHAR(32) NOT NULL,
  body_hash CHAR(64) NOT NULL,
  revision INT NOT NULL,
  firewall_json TEXT NOT NULL,
  status VARCHAR(32) NOT NULL,
  raw_private_payload_stored TINYINT(1) NOT NULL DEFAULT 0,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  KEY ix_matm_memory_workspace_scope (workspace_id, scope_type, scope_id),
  KEY ix_matm_memory_status (workspace_id, status, promotion_state),
  FULLTEXT KEY fx_matm_memory_text (title, public_safe_summary),
  CONSTRAINT fk_matm_memory_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_memory_revisions (
  revision_id VARCHAR(96) PRIMARY KEY,
  memory_id VARCHAR(96) NOT NULL,
  revision_number INT NOT NULL,
  public_safe_summary TEXT NOT NULL,
  change_summary TEXT NOT NULL,
  body_hash CHAR(64) NOT NULL,
  created_by_agent_id VARCHAR(128) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY ux_matm_memory_revision_number (memory_id, revision_number),
  CONSTRAINT fk_matm_memory_revisions_memory FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_memory_tags (
  memory_id VARCHAR(96) NOT NULL,
  tag VARCHAR(96) NOT NULL,
  PRIMARY KEY (memory_id, tag),
  KEY ix_matm_memory_tags_tag (tag),
  CONSTRAINT fk_matm_memory_tags_memory FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_crawl_sources (
  source_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  project_id VARCHAR(96) NULL,
  source_uri VARCHAR(512) NOT NULL,
  source_type VARCHAR(64) NOT NULL,
  crawl_policy VARCHAR(64) NOT NULL DEFAULT 'public_safe',
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  last_crawled_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_crawl_sources_workspace (workspace_id, status),
  CONSTRAINT fk_matm_crawl_sources_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_crawl_sources_project FOREIGN KEY (project_id) REFERENCES matm_projects (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_search_documents (
  search_document_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  memory_id VARCHAR(96) NULL,
  source_id VARCHAR(96) NULL,
  route_or_path VARCHAR(512) NULL,
  title VARCHAR(255) NOT NULL,
  searchable_text MEDIUMTEXT NOT NULL,
  visibility VARCHAR(32) NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_search_workspace_visibility (workspace_id, visibility),
  FULLTEXT KEY fx_matm_search_text (title, searchable_text),
  CONSTRAINT fk_matm_search_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_search_memory FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id),
  CONSTRAINT fk_matm_search_source FOREIGN KEY (source_id) REFERENCES matm_crawl_sources (source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_messages (
  message_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  sender_agent_id VARCHAR(128) NOT NULL,
  target_agent_id VARCHAR(128) NULL,
  safe_summary TEXT NOT NULL,
  response_required TINYINT(1) NOT NULL DEFAULT 0,
  raw_message_body_stored TINYINT(1) NOT NULL DEFAULT 0,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_messages_workspace_created (workspace_id, created_at),
  KEY ix_matm_messages_target (workspace_id, target_agent_id, created_at),
  CONSTRAINT fk_matm_messages_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_notifications (
  notification_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  message_id VARCHAR(96) NOT NULL,
  target_agent_id VARCHAR(128) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'unread',
  response_disposition VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at TIMESTAMP NULL,
  KEY ix_matm_notifications_target_status (workspace_id, target_agent_id, status),
  CONSTRAINT fk_matm_notifications_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_notifications_message FOREIGN KEY (message_id) REFERENCES matm_messages (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_receipts (
  receipt_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  notification_id VARCHAR(96) NOT NULL,
  consumer_agent_id VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_receipts_notification (notification_id),
  KEY ix_matm_receipts_consumer (workspace_id, consumer_agent_id),
  CONSTRAINT fk_matm_receipts_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_receipts_notification FOREIGN KEY (notification_id) REFERENCES matm_notifications (notification_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_review_queue (
  review_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  memory_id VARCHAR(96) NULL,
  proposed_by_agent_id VARCHAR(128) NULL,
  review_type VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  public_safe_summary TEXT NOT NULL,
  firewall_decision VARCHAR(64) NULL,
  risk_score INT NULL,
  detected_threats_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  decided_at TIMESTAMP NULL,
  reviewer_agent_id VARCHAR(128) NULL,
  reviewer_note_hash CHAR(64) NULL,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  KEY ix_matm_review_workspace_status (workspace_id, status),
  CONSTRAINT fk_matm_review_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_review_memory FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_idempotency (
  record_key VARCHAR(255) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  operation VARCHAR(96) NOT NULL,
  body_hash CHAR(64) NOT NULL,
  response_json MEDIUMTEXT NOT NULL,
  http_status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  idempotency_key_exposed TINYINT(1) NOT NULL DEFAULT 0,
  KEY ix_matm_idempotency_workspace (workspace_id),
  CONSTRAINT fk_matm_idempotency_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_outbox_events (
  outbox_event_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  event_type VARCHAR(96) NOT NULL,
  aggregate_type VARCHAR(96) NOT NULL,
  aggregate_id VARCHAR(96) NOT NULL,
  payload_hash CHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  KEY ix_matm_outbox_status_created (status, created_at),
  CONSTRAINT fk_matm_outbox_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_storage_ledger (
  ledger_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  object_type VARCHAR(64) NOT NULL,
  object_id VARCHAR(96) NOT NULL,
  bytes_delta BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  KEY ix_matm_storage_workspace_created (workspace_id, created_at),
  CONSTRAINT fk_matm_storage_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_audit_log (
  audit_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NULL,
  action VARCHAR(128) NOT NULL,
  actor VARCHAR(128) NULL,
  target VARCHAR(128) NULL,
  details_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_credential_exposed TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  KEY ix_matm_audit_workspace_created (workspace_id, created_at),
  CONSTRAINT fk_matm_audit_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
