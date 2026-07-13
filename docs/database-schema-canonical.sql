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
  history_retention_days INT NOT NULL DEFAULT 7,
  soft_deleted_at TIMESTAMP NULL,
  pre_delete_status VARCHAR(32) NULL,
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

CREATE TABLE IF NOT EXISTS matm_scope_nodes (
  scope_node_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NOT NULL,
  parent_scope_type VARCHAR(32) NULL,
  parent_scope_id VARCHAR(128) NULL,
  workspace_id VARCHAR(96) NULL,
  project_id VARCHAR(96) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY ux_matm_scope_nodes_identity (company_id, scope_type, scope_id),
  KEY ix_matm_scope_nodes_parent (company_id, parent_scope_type, parent_scope_id),
  CONSTRAINT fk_matm_scope_nodes_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_scope_nodes_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_scope_nodes_project FOREIGN KEY (project_id) REFERENCES matm_projects (project_id)
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

CREATE TABLE IF NOT EXISTS matm_company_master_keys (
  master_key_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  token_hash VARCHAR(80) NOT NULL,
  label VARCHAR(255) NOT NULL,
  principal_name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_company_master_keys_hash (token_hash),
  KEY ix_matm_company_master_keys_company (company_id, revoked_at),
  CONSTRAINT fk_matm_company_master_keys_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_human_owner_credentials (
  human_credential_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  token_hash VARCHAR(80) NOT NULL,
  principal_name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_human_owner_credentials_hash (token_hash),
  KEY ix_matm_human_owner_credentials_company (company_id, revoked_at),
  CONSTRAINT fk_matm_human_owner_credentials_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_human_sessions (
  human_session_id VARCHAR(96) PRIMARY KEY,
  human_credential_id VARCHAR(96) NOT NULL,
  company_id VARCHAR(96) NOT NULL,
  session_hash VARCHAR(80) NOT NULL,
  csrf_hash VARCHAR(80) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  last_seen_at TIMESTAMP NULL,
  reauthenticated_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_human_sessions_hash (session_hash),
  KEY ix_matm_human_sessions_company (company_id, revoked_at, expires_at),
  CONSTRAINT fk_matm_human_sessions_credential FOREIGN KEY (human_credential_id) REFERENCES matm_human_owner_credentials (human_credential_id),
  CONSTRAINT fk_matm_human_sessions_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_human_accounts (
  human_account_id VARCHAR(96) PRIMARY KEY,
  username VARCHAR(64) NOT NULL,
  username_normalized VARCHAR(64) NOT NULL,
  display_name VARCHAR(80) NOT NULL,
  password_verifier VARCHAR(512) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_human_accounts_username (username),
  UNIQUE KEY ux_matm_human_accounts_username_normalized (username_normalized)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_company_master_proofs (
  master_proof_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  master_key_id VARCHAR(96) NOT NULL,
  proof_hash VARCHAR(80) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'issued',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  consumed_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_company_master_proofs_hash (proof_hash),
  KEY ix_matm_company_master_proofs_company (company_id, status, expires_at),
  CONSTRAINT fk_matm_company_master_proofs_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_company_master_proofs_master FOREIGN KEY (master_key_id) REFERENCES matm_company_master_keys (master_key_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_human_company_authorities (
  authority_id VARCHAR(96) PRIMARY KEY,
  human_account_id VARCHAR(96) NOT NULL,
  company_id VARCHAR(96) NOT NULL,
  master_key_id VARCHAR(96) NOT NULL,
  role VARCHAR(32) NOT NULL,
  linked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  linked_by_account_id VARCHAR(96) NOT NULL,
  UNIQUE KEY ux_matm_human_company_authorities_account_company (human_account_id, company_id),
  KEY ix_matm_human_company_authorities_company (company_id, role),
  CONSTRAINT fk_matm_human_company_authorities_account FOREIGN KEY (human_account_id) REFERENCES matm_human_accounts (human_account_id),
  CONSTRAINT fk_matm_human_company_authorities_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_human_company_authorities_master FOREIGN KEY (master_key_id) REFERENCES matm_company_master_keys (master_key_id),
  CONSTRAINT fk_matm_human_company_authorities_linked_by FOREIGN KEY (linked_by_account_id) REFERENCES matm_human_accounts (human_account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_human_account_sessions (
  human_account_session_id VARCHAR(96) PRIMARY KEY,
  human_account_id VARCHAR(96) NOT NULL,
  selected_authority_id VARCHAR(96) NULL,
  selected_company_id VARCHAR(96) NULL,
  session_hash VARCHAR(80) NOT NULL,
  csrf_hash VARCHAR(80) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  last_seen_at TIMESTAMP NULL,
  password_reauthenticated_at TIMESTAMP NULL,
  rotated_from_session_id VARCHAR(96) NULL,
  revoked_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_human_account_sessions_hash (session_hash),
  KEY ix_matm_human_account_sessions_account (human_account_id, revoked_at, expires_at),
  CONSTRAINT fk_matm_human_account_sessions_account FOREIGN KEY (human_account_id) REFERENCES matm_human_accounts (human_account_id),
  CONSTRAINT fk_matm_human_account_sessions_authority FOREIGN KEY (selected_authority_id) REFERENCES matm_human_company_authorities (authority_id),
  CONSTRAINT fk_matm_human_account_sessions_company FOREIGN KEY (selected_company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_human_operational_contexts (
  human_account_session_id VARCHAR(96) PRIMARY KEY,
  human_account_id VARCHAR(96) NOT NULL,
  authority_id VARCHAR(96) NOT NULL,
  company_id VARCHAR(96) NOT NULL,
  workspace_id VARCHAR(96) NULL,
  project_id VARCHAR(96) NULL,
  context_version VARCHAR(96) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_human_operational_context_version (context_version),
  KEY ix_matm_human_operational_context_company (company_id, human_account_id),
  CONSTRAINT fk_matm_human_operational_context_session FOREIGN KEY (human_account_session_id) REFERENCES matm_human_account_sessions (human_account_session_id),
  CONSTRAINT fk_matm_human_operational_context_account FOREIGN KEY (human_account_id) REFERENCES matm_human_accounts (human_account_id),
  CONSTRAINT fk_matm_human_operational_context_authority FOREIGN KEY (authority_id) REFERENCES matm_human_company_authorities (authority_id),
  CONSTRAINT fk_matm_human_operational_context_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_human_operational_context_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_human_operational_context_project FOREIGN KEY (project_id) REFERENCES matm_projects (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_company_closure_intents (
  closure_intent_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  human_session_id VARCHAR(96) NOT NULL,
  auth_mode VARCHAR(32) NOT NULL DEFAULT 'human_account',
  intent_hash VARCHAR(80) NOT NULL,
  purpose VARCHAR(32) NOT NULL,
  typed_confirmation_phrase VARCHAR(255) NOT NULL,
  acknowledge_export_opportunity TINYINT(1) NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  consumed_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_company_closure_intents_hash (intent_hash),
  KEY ix_matm_company_closure_intents_company (company_id, purpose, status, expires_at),
  CONSTRAINT fk_matm_company_closure_intents_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_company_export_receipts (
  export_receipt_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  human_session_id VARCHAR(96) NOT NULL,
  artifact_digest VARCHAR(96) NOT NULL,
  artifact_format VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_company_export_receipts_company (company_id, created_at),
  CONSTRAINT fk_matm_company_export_receipts_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_company_export_receipts_session FOREIGN KEY (human_session_id) REFERENCES matm_human_account_sessions (human_account_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_agent_identities (
  agent_identity_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  agent_name VARCHAR(255) NOT NULL,
  agent_name_normalized VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_agent_identities_company_agent (company_id, agent_id),
  UNIQUE KEY ux_matm_agent_identities_company_name (company_id, agent_name_normalized),
  KEY ix_matm_agent_identities_company (company_id, status),
  CONSTRAINT fk_matm_agent_identities_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_connector_rate_limits (
  bucket VARCHAR(48) NOT NULL,
  partition_hash CHAR(64) NOT NULL,
  window_started_at_epoch BIGINT NOT NULL,
  expires_at_epoch BIGINT NOT NULL,
  request_count INT NOT NULL,
  request_limit INT NOT NULL,
  window_seconds INT NOT NULL,
  updated_at_epoch BIGINT NOT NULL,
  PRIMARY KEY (bucket, partition_hash),
  KEY ix_matm_connector_rate_limits_expiry (expires_at_epoch)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_connector_pairing_requests (
  request_id VARCHAR(96) PRIMARY KEY,
  public_request_ref CHAR(51) NOT NULL,
  pairing_request_proof_verifier VARCHAR(96) NOT NULL,
  request_idempotency_key_hash VARCHAR(96) NOT NULL,
  request_digest VARCHAR(96) NOT NULL,
  request_idempotency_digest VARCHAR(96) NOT NULL,
  client_id VARCHAR(96) NOT NULL,
  redirect_uri VARCHAR(512) NOT NULL,
  state_verifier VARCHAR(96) NOT NULL,
  code_challenge VARCHAR(128) NOT NULL,
  code_challenge_method VARCHAR(16) NOT NULL,
  requested_agent_id VARCHAR(128) NOT NULL,
  requested_scopes_json TEXT NOT NULL,
  approved_scopes_json TEXT NULL,
  scope_digest VARCHAR(96) NOT NULL,
  approved_agent_id VARCHAR(128) NULL,
  company_id VARCHAR(96) NULL,
  workspace_id VARCHAR(96) NULL,
  project_id VARCHAR(96) NULL,
  workspace_mode VARCHAR(32) NULL,
  provisional_workspace TINYINT(1) NOT NULL DEFAULT 0,
  workspace_label VARCHAR(255) NULL,
  project_label VARCHAR(255) NULL,
  status VARCHAR(48) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  approved_at TIMESTAMP NULL,
  approved_by_human_account_id VARCHAR(96) NULL,
  approved_by_authority_id VARCHAR(96) NULL,
  approval_idempotency_key_hash VARCHAR(96) NULL,
  approval_request_digest VARCHAR(96) NULL,
  approval_idempotency_digest VARCHAR(96) NULL,
  authorization_code_id VARCHAR(96) NULL,
  authorization_code_verifier VARCHAR(96) NULL,
  authorization_code_expires_at TIMESTAMP NULL,
  authorization_code_claimed_at TIMESTAMP NULL,
  authorization_code_consumed_at TIMESTAMP NULL,
  claim_idempotency_key_hash VARCHAR(96) NULL,
  claim_request_digest VARCHAR(96) NULL,
  claim_idempotency_digest VARCHAR(96) NULL,
  exchange_idempotency_key_hash VARCHAR(96) NULL,
  exchange_request_digest VARCHAR(96) NULL,
  exchange_idempotency_digest VARCHAR(96) NULL,
  human_cancellation_idempotency_key_hash VARCHAR(96) NULL,
  human_cancellation_request_digest VARCHAR(96) NULL,
  human_cancellation_idempotency_digest VARCHAR(96) NULL,
  human_cancelled_at TIMESTAMP NULL,
  human_cancelled_by_account_id VARCHAR(96) NULL,
  human_cancellation_reason VARCHAR(255) NULL,
  UNIQUE KEY ux_matm_connector_requests_public_ref (public_request_ref),
  UNIQUE KEY ux_matm_connector_requests_proof (pairing_request_proof_verifier),
  UNIQUE KEY ux_matm_connector_requests_idempotency (request_idempotency_key_hash),
  UNIQUE KEY ux_matm_connector_requests_code_id (authorization_code_id),
  UNIQUE KEY ux_matm_connector_requests_code_verifier (authorization_code_verifier),
  KEY ix_matm_connector_requests_status (status, expires_at),
  KEY ix_matm_connector_requests_company_agent (company_id, approved_agent_id, status),
  CONSTRAINT fk_matm_connector_requests_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_connector_requests_human FOREIGN KEY (approved_by_human_account_id) REFERENCES matm_human_accounts (human_account_id),
  CONSTRAINT fk_matm_connector_requests_authority FOREIGN KEY (approved_by_authority_id) REFERENCES matm_human_company_authorities (authority_id),
  CONSTRAINT fk_matm_connector_requests_cancel_human FOREIGN KEY (human_cancelled_by_account_id) REFERENCES matm_human_accounts (human_account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_connector_pairings (
  pairing_id VARCHAR(96) PRIMARY KEY,
  request_id VARCHAR(96) NOT NULL,
  company_id VARCHAR(96) NOT NULL,
  workspace_id VARCHAR(96) NOT NULL,
  project_id VARCHAR(96) NULL,
  agent_id VARCHAR(128) NOT NULL,
  agent_identity_id VARCHAR(96) NULL,
  workspace_mode VARCHAR(32) NOT NULL,
  provisional_workspace TINYINT(1) NOT NULL DEFAULT 0,
  workspace_label VARCHAR(255) NULL,
  project_label VARCHAR(255) NULL,
  status VARCHAR(48) NOT NULL,
  approved_scopes_json TEXT NOT NULL,
  scope_digest VARCHAR(96) NOT NULL,
  current_credential_id VARCHAR(96) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  activation_expires_at TIMESTAMP NULL,
  activated_at TIMESTAMP NULL,
  ended_at TIMESTAMP NULL,
  ended_reason VARCHAR(255) NULL,
  revoked_by_master_key_id VARCHAR(96) NULL,
  activation_idempotency_key_hash VARCHAR(96) NULL,
  activation_request_digest VARCHAR(96) NULL,
  activation_idempotency_digest VARCHAR(96) NULL,
  revocation_idempotency_key_hash VARCHAR(96) NULL,
  revocation_request_digest VARCHAR(96) NULL,
  revocation_idempotency_digest VARCHAR(96) NULL,
  disconnect_idempotency_key_hash VARCHAR(96) NULL,
  disconnect_request_digest VARCHAR(96) NULL,
  disconnect_idempotency_digest VARCHAR(96) NULL,
  cancellation_idempotency_key_hash VARCHAR(96) NULL,
  cancellation_request_digest VARCHAR(96) NULL,
  cancellation_idempotency_digest VARCHAR(96) NULL,
  UNIQUE KEY ux_matm_connector_pairings_request (request_id),
  KEY ix_matm_connector_pairings_company_agent (company_id, agent_id, status),
  KEY ix_matm_connector_pairings_pending (status, activation_expires_at),
  CONSTRAINT fk_matm_connector_pairings_request FOREIGN KEY (request_id) REFERENCES matm_connector_pairing_requests (request_id),
  CONSTRAINT fk_matm_connector_pairings_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_connector_pairings_identity FOREIGN KEY (agent_identity_id) REFERENCES matm_agent_identities (agent_identity_id),
  CONSTRAINT fk_matm_connector_pairings_master FOREIGN KEY (revoked_by_master_key_id) REFERENCES matm_company_master_keys (master_key_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_connector_credentials (
  credential_id VARCHAR(96) PRIMARY KEY,
  pairing_id VARCHAR(96) NOT NULL,
  credential_verifier VARCHAR(96) NOT NULL,
  approved_scopes_json TEXT NOT NULL,
  scope_digest VARCHAR(96) NOT NULL,
  status VARCHAR(48) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  activated_at TIMESTAMP NULL,
  last_used_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  raw_credential_persisted TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_connector_credentials_verifier (credential_verifier),
  KEY ix_matm_connector_credentials_pairing (pairing_id, status),
  CONSTRAINT fk_matm_connector_credentials_pairing FOREIGN KEY (pairing_id) REFERENCES matm_connector_pairings (pairing_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_connector_rotations (
  rotation_id VARCHAR(96) PRIMARY KEY,
  pairing_id VARCHAR(96) NOT NULL,
  predecessor_credential_id VARCHAR(96) NOT NULL,
  successor_credential_id VARCHAR(96) NOT NULL,
  status VARCHAR(48) NOT NULL,
  approved_scopes_json TEXT NOT NULL,
  scope_digest VARCHAR(96) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  prepare_idempotency_key_hash VARCHAR(96) NOT NULL,
  prepare_request_digest VARCHAR(96) NOT NULL,
  prepare_idempotency_digest VARCHAR(96) NOT NULL,
  activation_idempotency_key_hash VARCHAR(96) NULL,
  activation_request_digest VARCHAR(96) NULL,
  activation_idempotency_digest VARCHAR(96) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  activation_expires_at TIMESTAMP NULL,
  activated_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_connector_rotations_successor (successor_credential_id),
  KEY ix_matm_connector_rotations_pairing (pairing_id, status, activation_expires_at),
  CONSTRAINT fk_matm_connector_rotations_pairing FOREIGN KEY (pairing_id) REFERENCES matm_connector_pairings (pairing_id),
  CONSTRAINT fk_matm_connector_rotations_predecessor FOREIGN KEY (predecessor_credential_id) REFERENCES matm_connector_credentials (credential_id),
  CONSTRAINT fk_matm_connector_rotations_successor FOREIGN KEY (successor_credential_id) REFERENCES matm_connector_credentials (credential_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_agent_access_requests (
  request_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  agent_name VARCHAR(255) NOT NULL,
  agent_name_normalized VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  justification TEXT NOT NULL,
  assignment_context_json TEXT NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NOT NULL,
  requested_by VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  supersedes_token_id VARCHAR(96) NULL,
  memory_transfer_from_token_id VARCHAR(96) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  approved_at TIMESTAMP NULL,
  approved_by_master_key_id VARCHAR(96) NULL,
  denied_at TIMESTAMP NULL,
  denied_by_master_key_id VARCHAR(96) NULL,
  agent_identity_id VARCHAR(96) NULL,
  invite_id VARCHAR(96) NULL,
  decision_reason TEXT NULL,
  KEY ix_matm_agent_access_requests_company_status (company_id, status, created_at),
  CONSTRAINT fk_matm_agent_access_requests_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_agent_access_requests_approved_master FOREIGN KEY (approved_by_master_key_id) REFERENCES matm_company_master_keys (master_key_id),
  CONSTRAINT fk_matm_agent_access_requests_denied_master FOREIGN KEY (denied_by_master_key_id) REFERENCES matm_company_master_keys (master_key_id),
  CONSTRAINT fk_matm_agent_access_requests_identity FOREIGN KEY (agent_identity_id) REFERENCES matm_agent_identities (agent_identity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_agent_invites (
  invite_id VARCHAR(96) PRIMARY KEY,
  request_id VARCHAR(96) NOT NULL,
  company_id VARCHAR(96) NOT NULL,
  agent_identity_id VARCHAR(96) NOT NULL,
  token_hash VARCHAR(80) NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'issued',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  redeemed_at TIMESTAMP NULL,
  approved_by_master_key_id VARCHAR(96) NOT NULL,
  revoked_at TIMESTAMP NULL,
  revoked_by_master_key_id VARCHAR(96) NULL,
  grant_id VARCHAR(96) NULL,
  agent_token_id VARCHAR(96) NULL,
  assignment_context_json TEXT NOT NULL,
  UNIQUE KEY ux_matm_agent_invites_request (request_id),
  UNIQUE KEY ux_matm_agent_invites_hash (token_hash),
  KEY ix_matm_agent_invites_company_status (company_id, status, expires_at),
  CONSTRAINT fk_matm_agent_invites_request FOREIGN KEY (request_id) REFERENCES matm_agent_access_requests (request_id),
  CONSTRAINT fk_matm_agent_invites_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_agent_invites_identity FOREIGN KEY (agent_identity_id) REFERENCES matm_agent_identities (agent_identity_id),
  CONSTRAINT fk_matm_agent_invites_approved_master FOREIGN KEY (approved_by_master_key_id) REFERENCES matm_company_master_keys (master_key_id),
  CONSTRAINT fk_matm_agent_invites_revoked_master FOREIGN KEY (revoked_by_master_key_id) REFERENCES matm_company_master_keys (master_key_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_agent_access_grants (
  grant_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  agent_identity_id VARCHAR(96) NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NOT NULL,
  workspace_id VARCHAR(96) NULL,
  project_id VARCHAR(96) NULL,
  supersedes_token_id VARCHAR(96) NULL,
  memory_transfer_from_token_id VARCHAR(96) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  pending_expires_at TIMESTAMP NULL,
  predecessor_token_id VARCHAR(96) NULL,
  activated_at TIMESTAMP NULL,
  cancelled_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  revoked_by_master_key_id VARCHAR(96) NULL,
  KEY ix_matm_agent_access_grants_identity (agent_identity_id, status),
  KEY ix_matm_agent_access_grants_scope (company_id, scope_type, scope_id, status),
  CONSTRAINT fk_matm_agent_access_grants_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_agent_access_grants_identity FOREIGN KEY (agent_identity_id) REFERENCES matm_agent_identities (agent_identity_id),
  CONSTRAINT fk_matm_agent_access_grants_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_agent_access_grants_project FOREIGN KEY (project_id) REFERENCES matm_projects (project_id),
  CONSTRAINT fk_matm_agent_access_grants_revoked_master FOREIGN KEY (revoked_by_master_key_id) REFERENCES matm_company_master_keys (master_key_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_agent_tokens (
  agent_token_id VARCHAR(96) PRIMARY KEY,
  grant_id VARCHAR(96) NOT NULL,
  agent_identity_id VARCHAR(96) NOT NULL,
  token_hash VARCHAR(80) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_agent_tokens_grant (grant_id),
  UNIQUE KEY ux_matm_agent_tokens_hash (token_hash),
  KEY ix_matm_agent_tokens_identity (agent_identity_id, revoked_at),
  CONSTRAINT fk_matm_agent_tokens_grant FOREIGN KEY (grant_id) REFERENCES matm_agent_access_grants (grant_id),
  CONSTRAINT fk_matm_agent_tokens_identity FOREIGN KEY (agent_identity_id) REFERENCES matm_agent_identities (agent_identity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_agent_token_replacements (
  replacement_id VARCHAR(96) PRIMARY KEY,
  company_id VARCHAR(96) NOT NULL,
  human_account_id VARCHAR(96) NOT NULL,
  authority_id VARCHAR(96) NOT NULL,
  predecessor_credential_id VARCHAR(96) NOT NULL,
  successor_credential_id VARCHAR(96) NOT NULL,
  successor_grant_id VARCHAR(96) NOT NULL,
  agent_identity_id VARCHAR(96) NOT NULL,
  reason VARCHAR(255) NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL DEFAULT 'prepared',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  prepare_idempotency_hash CHAR(64) NULL,
  prepare_request_digest CHAR(64) NULL,
  successor_delivered_at TIMESTAMP NULL,
  confirm_idempotency_hash CHAR(64) NULL,
  confirm_request_digest CHAR(64) NULL,
  confirmed_at TIMESTAMP NULL,
  cancel_idempotency_hash CHAR(64) NULL,
  cancel_request_digest CHAR(64) NULL,
  canceled_at TIMESTAMP NULL,
  revoked_credential_id VARCHAR(96) NULL,
  activated_credential_id VARCHAR(96) NULL,
  UNIQUE KEY ux_matm_agent_token_replacements_successor (successor_credential_id),
  UNIQUE KEY ux_matm_agent_token_replacements_grant (successor_grant_id),
  UNIQUE KEY ux_matm_agent_token_replacements_prepare_idem (company_id, prepare_idempotency_hash),
  KEY ix_matm_agent_token_replacements_company (company_id, status, expires_at),
  KEY ix_matm_agent_token_replacements_predecessor (predecessor_credential_id, status),
  CONSTRAINT fk_matm_agent_token_replacements_company FOREIGN KEY (company_id) REFERENCES matm_companies (company_id),
  CONSTRAINT fk_matm_agent_token_replacements_human FOREIGN KEY (human_account_id) REFERENCES matm_human_accounts (human_account_id),
  CONSTRAINT fk_matm_agent_token_replacements_authority FOREIGN KEY (authority_id) REFERENCES matm_human_company_authorities (authority_id),
  CONSTRAINT fk_matm_agent_token_replacements_predecessor FOREIGN KEY (predecessor_credential_id) REFERENCES matm_agent_tokens (agent_token_id),
  CONSTRAINT fk_matm_agent_token_replacements_successor FOREIGN KEY (successor_credential_id) REFERENCES matm_agent_tokens (agent_token_id),
  CONSTRAINT fk_matm_agent_token_replacements_grant FOREIGN KEY (successor_grant_id) REFERENCES matm_agent_access_grants (grant_id),
  CONSTRAINT fk_matm_agent_token_replacements_identity FOREIGN KEY (agent_identity_id) REFERENCES matm_agent_identities (agent_identity_id)
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

CREATE TABLE IF NOT EXISTS matm_uai_packages (
  package_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  agent_record_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  agent_name VARCHAR(255) NOT NULL,
  profile VARCHAR(96) NOT NULL,
  package_type VARCHAR(96) NOT NULL,
  client_class VARCHAR(96) NOT NULL,
  local_filesystem_available TINYINT(1) NOT NULL DEFAULT 0,
  storage_mode VARCHAR(96) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'setup_required',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_credential_exposed TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_uai_packages_agent_profile (workspace_id, agent_id, profile),
  KEY ix_matm_uai_packages_agent (workspace_id, agent_id, status),
  CONSTRAINT fk_matm_uai_packages_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_uai_packages_agent FOREIGN KEY (agent_record_id) REFERENCES matm_agents (agent_record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_uai_records (
  record_id VARCHAR(96) PRIMARY KEY,
  package_id VARCHAR(96) NOT NULL,
  workspace_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  logical_path VARCHAR(255) NOT NULL,
  role VARCHAR(96) NOT NULL,
  title VARCHAR(255) NOT NULL,
  content MEDIUMTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  content_bytes BIGINT NOT NULL,
  revision INT NOT NULL,
  required_record TINYINT(1) NOT NULL DEFAULT 0,
  startup_order INT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  source_uri VARCHAR(512) NOT NULL,
  firewall_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_credential_exposed TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_uai_records_package_path (package_id, logical_path),
  KEY ix_matm_uai_records_startup (workspace_id, package_id, status, startup_order),
  CONSTRAINT fk_matm_uai_records_package FOREIGN KEY (package_id) REFERENCES matm_uai_packages (package_id),
  CONSTRAINT fk_matm_uai_records_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_uai_record_revisions (
  revision_id VARCHAR(96) PRIMARY KEY,
  record_id VARCHAR(96) NOT NULL,
  package_id VARCHAR(96) NOT NULL,
  workspace_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  logical_path VARCHAR(255) NOT NULL,
  revision INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  content MEDIUMTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_credential_exposed TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_uai_revisions_record_number (record_id, revision),
  KEY ix_matm_uai_revisions_record (workspace_id, record_id, revision),
  CONSTRAINT fk_matm_uai_revisions_record FOREIGN KEY (record_id) REFERENCES matm_uai_records (record_id),
  CONSTRAINT fk_matm_uai_revisions_package FOREIGN KEY (package_id) REFERENCES matm_uai_packages (package_id),
  CONSTRAINT fk_matm_uai_revisions_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_uai_collaboration_heads (
  head_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  project_id VARCHAR(96) NOT NULL,
  logical_path VARCHAR(255) NOT NULL,
  observed_content_hash CHAR(64) NOT NULL,
  revision INT NOT NULL DEFAULT 0,
  active_claim_id VARCHAR(96) NULL,
  active_agent_id VARCHAR(128) NULL,
  lease_expires_at TIMESTAMP NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'tracked',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_credential_exposed TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_uai_heads_project_path (workspace_id, project_id, logical_path),
  KEY ix_matm_uai_heads_project (workspace_id, project_id, logical_path),
  CONSTRAINT fk_matm_uai_heads_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_uai_heads_project FOREIGN KEY (project_id) REFERENCES matm_projects (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_uai_edit_claims (
  claim_id VARCHAR(96) PRIMARY KEY,
  head_id VARCHAR(96) NOT NULL,
  workspace_id VARCHAR(96) NOT NULL,
  project_id VARCHAR(96) NOT NULL,
  agent_record_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  agent_name VARCHAR(255) NOT NULL,
  logical_path VARCHAR(255) NOT NULL,
  base_content_hash CHAR(64) NOT NULL,
  intent_summary TEXT NOT NULL,
  lease_seconds INT NOT NULL,
  lease_expires_at TIMESTAMP NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  completion_content_hash CHAR(64) NULL,
  completion_summary TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at TIMESTAMP NULL,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_credential_exposed TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  KEY ix_matm_uai_claims_active (workspace_id, project_id, status, lease_expires_at),
  KEY ix_matm_uai_claims_agent (workspace_id, agent_id, created_at),
  CONSTRAINT fk_matm_uai_claims_head FOREIGN KEY (head_id) REFERENCES matm_uai_collaboration_heads (head_id),
  CONSTRAINT fk_matm_uai_claims_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_uai_claims_project FOREIGN KEY (project_id) REFERENCES matm_projects (project_id),
  CONSTRAINT fk_matm_uai_claims_agent FOREIGN KEY (agent_record_id) REFERENCES matm_agents (agent_record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_memory_records (
  memory_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  actor_agent_id VARCHAR(128) NULL,
  human_account_id VARCHAR(96) NULL,
  human_account_session_id VARCHAR(96) NULL,
  human_username VARCHAR(64) NULL,
  human_authority_id VARCHAR(96) NULL,
  human_company_id VARCHAR(96) NULL,
  auth_mode VARCHAR(32) NOT NULL DEFAULT 'agent',
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
  CONSTRAINT fk_matm_memory_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_memory_human_account FOREIGN KEY (human_account_id) REFERENCES matm_human_accounts (human_account_id),
  CONSTRAINT fk_matm_memory_human_session FOREIGN KEY (human_account_session_id) REFERENCES matm_human_account_sessions (human_account_session_id),
  CONSTRAINT fk_matm_memory_human_authority FOREIGN KEY (human_authority_id) REFERENCES matm_human_company_authorities (authority_id),
  CONSTRAINT fk_matm_memory_human_company FOREIGN KEY (human_company_id) REFERENCES matm_companies (company_id)
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
  scope_type VARCHAR(32) NOT NULL DEFAULT 'workspace',
  scope_id VARCHAR(128) NULL,
  category VARCHAR(96) NULL,
  document_type VARCHAR(64) NOT NULL DEFAULT 'knowledge_document',
  route_or_path VARCHAR(512) NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT NULL,
  keywords_json TEXT NULL,
  taxonomy_paths_json TEXT NULL,
  knowledge_status VARCHAR(32) NOT NULL DEFAULT 'current',
  authority_level VARCHAR(32) NOT NULL DEFAULT 'reviewed',
  status_reason TEXT NULL,
  superseded_by_document_id VARCHAR(96) NULL,
  searchable_text MEDIUMTEXT NOT NULL,
  visibility VARCHAR(32) NOT NULL,
  content_hash CHAR(64) NOT NULL DEFAULT '',
  metadata_json TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_search_workspace_visibility (workspace_id, visibility),
  KEY ix_matm_search_workspace_scope (workspace_id, scope_type, scope_id),
  KEY ix_matm_search_workspace_lifecycle (workspace_id, knowledge_status, authority_level),
  FULLTEXT KEY fx_matm_search_text (title, searchable_text),
  CONSTRAINT fk_matm_search_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_search_memory FOREIGN KEY (memory_id) REFERENCES matm_memory_records (memory_id),
  CONSTRAINT fk_matm_search_source FOREIGN KEY (source_id) REFERENCES matm_crawl_sources (source_id),
  CONSTRAINT fk_matm_search_superseded_by FOREIGN KEY (superseded_by_document_id) REFERENCES matm_search_documents (search_document_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_external_links (
  external_link_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  url TEXT NOT NULL,
  normalized_url TEXT NOT NULL,
  normalized_url_hash CHAR(64) NOT NULL,
  page_url TEXT NOT NULL,
  fragment TEXT NULL,
  scheme VARCHAR(8) NOT NULL,
  host VARCHAR(255) NOT NULL,
  site_name VARCHAR(255) NOT NULL,
  page_title VARCHAR(512) NOT NULL,
  description TEXT NOT NULL,
  keywords_json TEXT NOT NULL,
  language VARCHAR(16) NOT NULL DEFAULT 'und',
  content_type VARCHAR(128) NOT NULL DEFAULT 'text/html',
  review_status VARCHAR(32) NOT NULL DEFAULT 'unreviewed',
  crawl_status VARCHAR(32) NOT NULL DEFAULT 'not_requested',
  crawl_policy VARCHAR(64) NOT NULL DEFAULT 'metadata_only',
  visibility VARCHAR(32) NOT NULL DEFAULT 'workspace_private',
  metadata_json TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY ux_matm_external_links_url_hash (workspace_id, normalized_url_hash),
  KEY ix_matm_external_links_host (workspace_id, host),
  KEY ix_matm_external_links_review (workspace_id, review_status, crawl_status),
  CONSTRAINT fk_matm_external_links_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_external_link_mentions (
  external_link_mention_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  external_link_id VARCHAR(96) NOT NULL,
  search_document_id VARCHAR(96) NOT NULL,
  relationship_type VARCHAR(32) NOT NULL DEFAULT 'reference',
  anchor_text TEXT NOT NULL,
  context_description TEXT NOT NULL,
  citation_label VARCHAR(64) NULL,
  citation_order INT NOT NULL DEFAULT 0,
  source_report_name VARCHAR(512) NOT NULL DEFAULT '',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY ux_matm_external_link_mention (workspace_id, external_link_id, search_document_id, relationship_type, citation_label),
  KEY ix_matm_external_link_mentions_document (workspace_id, search_document_id, citation_order),
  CONSTRAINT fk_matm_external_link_mentions_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_external_link_mentions_link FOREIGN KEY (external_link_id) REFERENCES matm_external_links (external_link_id),
  CONSTRAINT fk_matm_external_link_mentions_document FOREIGN KEY (search_document_id) REFERENCES matm_search_documents (search_document_id)
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

CREATE TABLE IF NOT EXISTS matm_meeting_rooms (
  room_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NOT NULL,
  label VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  purpose TEXT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  default_room TINYINT(1) NOT NULL DEFAULT 1,
  always_available TINYINT(1) NOT NULL DEFAULT 1,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_meeting_room_scope (workspace_id, scope_type, scope_id),
  KEY ix_matm_meeting_rooms_scope (workspace_id, scope_type, scope_id),
  CONSTRAINT fk_matm_meeting_rooms_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_meeting_messages (
  meeting_message_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  room_id VARCHAR(96) NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NOT NULL,
  sender_agent_id VARCHAR(128) NOT NULL,
  safe_summary TEXT NOT NULL,
  raw_message_body_stored TINYINT(1) NOT NULL DEFAULT 0,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_meeting_messages_room_created (workspace_id, room_id, created_at),
  CONSTRAINT fk_matm_meeting_messages_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_meeting_messages_room FOREIGN KEY (room_id) REFERENCES matm_meeting_rooms (room_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_routing_decisions (
  routing_decision_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  source_room_id VARCHAR(96) NOT NULL,
  destination_room_id VARCHAR(96) NOT NULL,
  destination_scope VARCHAR(32) NOT NULL,
  destination_scope_id VARCHAR(128) NOT NULL,
  coordinator_agent_id VARCHAR(128) NOT NULL,
  routed_agent_id VARCHAR(128) NOT NULL,
  lane VARCHAR(96) NOT NULL,
  specific_goal TEXT NOT NULL,
  expected_evidence_json TEXT NOT NULL,
  next_action TEXT NOT NULL,
  support_plan TEXT NOT NULL,
  meeting_message_id VARCHAR(96) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_matm_routing_decisions_agent (workspace_id, routed_agent_id, created_at),
  KEY ix_matm_routing_decisions_destination (workspace_id, destination_room_id, created_at),
  KEY ix_matm_routing_decisions_status (workspace_id, status, created_at),
  CONSTRAINT fk_matm_routing_decisions_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_routing_decisions_source_room FOREIGN KEY (source_room_id) REFERENCES matm_meeting_rooms (room_id),
  CONSTRAINT fk_matm_routing_decisions_destination_room FOREIGN KEY (destination_room_id) REFERENCES matm_meeting_rooms (room_id),
  CONSTRAINT fk_matm_routing_decisions_message FOREIGN KEY (meeting_message_id) REFERENCES matm_meeting_messages (meeting_message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_meeting_reads (
  meeting_read_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  room_id VARCHAR(96) NOT NULL,
  agent_id VARCHAR(128) NOT NULL,
  last_meeting_message_id VARCHAR(96) NULL,
  last_read_at TIMESTAMP NULL,
  read_message_count INT NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'read',
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  UNIQUE KEY ux_matm_meeting_read_agent (workspace_id, room_id, agent_id),
  KEY ix_matm_meeting_reads_agent (workspace_id, agent_id),
  CONSTRAINT fk_matm_meeting_reads_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_meeting_reads_room FOREIGN KEY (room_id) REFERENCES matm_meeting_rooms (room_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_sync_devices (
  device_record_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  device_id VARCHAR(128) NOT NULL,
  agent_id VARCHAR(128) NULL,
  label VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  authority_epoch INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_sync_device_workspace (workspace_id, device_id),
  KEY ix_matm_sync_devices_workspace (workspace_id, status),
  CONSTRAINT fk_matm_sync_devices_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_sync_heads (
  head_record_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  logical_memory_id VARCHAR(128) NOT NULL,
  head_revision_id VARCHAR(96) NULL,
  server_sequence BIGINT NOT NULL,
  indexed_through_sequence BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_sync_heads_logical (workspace_id, logical_memory_id),
  KEY ix_matm_sync_heads_workspace (workspace_id, status),
  CONSTRAINT fk_matm_sync_heads_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_sync_revisions (
  sync_revision_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  logical_memory_id VARCHAR(128) NOT NULL,
  parent_revision_id VARCHAR(96) NULL,
  memory_event_id VARCHAR(96) NULL,
  actor_agent_id VARCHAR(128) NULL,
  device_id VARCHAR(128) NULL,
  device_epoch INT NOT NULL DEFAULT 0,
  operation VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  conflict TINYINT(1) NOT NULL DEFAULT 0,
  conflict_code VARCHAR(96) NULL,
  server_sequence BIGINT NOT NULL,
  body_hash CHAR(64) NOT NULL,
  source_uri VARCHAR(512) NULL,
  title VARCHAR(255) NOT NULL,
  public_safe_summary TEXT NOT NULL,
  scope_type VARCHAR(32) NOT NULL,
  scope_id VARCHAR(128) NULL,
  memory_type VARCHAR(32) NOT NULL,
  tombstone TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_sync_revisions_sequence (workspace_id, server_sequence),
  KEY ix_matm_sync_revisions_logical (workspace_id, logical_memory_id, server_sequence),
  CONSTRAINT fk_matm_sync_revisions_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matm_sync_receipts (
  receipt_id VARCHAR(96) PRIMARY KEY,
  workspace_id VARCHAR(96) NOT NULL,
  idempotency_key_hash VARCHAR(80) NULL,
  body_hash CHAR(64) NOT NULL,
  logical_memory_id VARCHAR(128) NULL,
  sync_revision_id VARCHAR(96) NULL,
  server_sequence BIGINT NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL,
  conflict TINYINT(1) NOT NULL DEFAULT 0,
  conflict_code VARCHAR(96) NULL,
  current_head_revision_id VARCHAR(96) NULL,
  http_status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  idempotency_key_exposed TINYINT(1) NOT NULL DEFAULT 0,
  values_redacted TINYINT(1) NOT NULL DEFAULT 1,
  raw_credential_exposed TINYINT(1) NOT NULL DEFAULT 0,
  raw_payload_exposed TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY ux_matm_sync_receipts_idem (workspace_id, idempotency_key_hash),
  KEY ix_matm_sync_receipts_workspace (workspace_id, created_at),
  CONSTRAINT fk_matm_sync_receipts_workspace FOREIGN KEY (workspace_id) REFERENCES matm_workspaces (workspace_id),
  CONSTRAINT fk_matm_sync_receipts_revision FOREIGN KEY (sync_revision_id) REFERENCES matm_sync_revisions (sync_revision_id)
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
