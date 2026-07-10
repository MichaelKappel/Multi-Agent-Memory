# Database Structure

The authoritative relational proposal is `docs/database-schema-canonical.sql`.

The schema is organized around MATM responsibilities:

- Account and organization boundary: `matm_accounts`, `matm_companies`, `matm_account_companies`, `matm_workspaces`, `matm_projects`
- Access boundary: `matm_api_keys`, `matm_agents`
- Durable memory: `matm_memory_records`, `matm_memory_revisions`, `matm_memory_tags`
- Crawlable/searchable memory: `matm_crawl_sources`, `matm_search_documents`
- Current-message lane: `matm_messages`, `matm_notifications`, `matm_receipts`
- Meeting rooms: `matm_meeting_rooms`, `matm_meeting_messages`, `matm_meeting_reads`
- Human review and promotion: `matm_review_queue`
- Retry safety and asynchronous processing: `matm_idempotency`, `matm_outbox_events`
- Quota and transparency: `matm_storage_ledger`, `matm_audit_log`

Runtime state today:

- File backend: live default.
- SQLite backend: live stdlib relational database-backed option for the implemented MATM workflows. The runtime creates separate SQLite tables for accounts, companies, account-company memberships, workspaces, projects, API keys, agents, memory records, memory revisions, tags, crawl sources, search documents, review queue, messages, notifications, receipts, meeting rooms, meeting messages, meeting read cursors, idempotency records, outbox events, storage ledger entries, and audit logs.
- MySQL/MariaDB: required for production completion; `/api/version` must report `storeBackend` as `mysql` or `mariadb` and `storeBackendVerified` as `true`.

Design rules:

- Store public-safe summaries instead of raw private payloads.
- Store token hashes, never raw API keys.
- Model `project -> workspace -> company`, and model accounts as many-to-many company memberships.
- Keep current messages separate from promoted durable memory.
- Model company, workspace, and project meeting rooms as first-class durable objects, not as ad hoc current-message broadcasts or UI-only labels.
- Record review/promotion decisions before company, workspace, or project long-term memory is treated as authoritative.
- Use idempotency records for protected mutation retries.
- Use storage ledger entries to enforce the 200 MB free account quota.
