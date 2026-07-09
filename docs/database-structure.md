# Database Structure

The authoritative relational proposal is `docs/database-schema-canonical.sql`.

The schema is organized around MATM responsibilities:

- Account boundary: `matm_clients`, `matm_workspaces`, `matm_projects`
- Access boundary: `matm_api_keys`, `matm_agents`
- Durable memory: `matm_memory_records`, `matm_memory_revisions`, `matm_memory_tags`
- Crawlable/searchable memory: `matm_crawl_sources`, `matm_search_documents`
- Current-message lane: `matm_messages`, `matm_notifications`, `matm_receipts`
- Human review and promotion: `matm_review_queue`
- Retry safety and asynchronous processing: `matm_idempotency`, `matm_outbox_events`
- Quota and transparency: `matm_storage_ledger`, `matm_audit_log`

Runtime state today:

- File backend: live default.
- SQLite backend: live stdlib database-backed option.
- MySQL/MariaDB: schema prepared, adapter gated by the no-third-party runtime requirement.

Design rules:

- Store public-safe summaries instead of raw private payloads.
- Store token hashes, never raw API keys.
- Keep current messages separate from promoted durable memory.
- Record review/promotion decisions before client, workspace, or project long-term memory is treated as authoritative.
- Use idempotency records for protected mutation retries.
- Use storage ledger entries to enforce the 200 MB free account quota.
