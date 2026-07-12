# Database Structure

The canonical relational schema is `docs/database-schema-canonical.sql`. The runtime initializes the implemented SQLite and MySQL/MariaDB tables from the same ownership model.

The schema is organized around MATM responsibilities:

- Account and organization boundary: `matm_accounts`, `matm_companies`, `matm_account_companies`, `matm_workspaces`, `matm_projects`
- Access boundary: `matm_api_keys`, `matm_agents`
- Durable memory: `matm_memory_records`, `matm_memory_revisions`, `matm_memory_tags`
- Crawlable/searchable knowledge wiki: `matm_crawl_sources`, `matm_search_documents`
- Curated web index and citations: `matm_external_links`, `matm_external_link_mentions`
- Current-message lane: `matm_messages`, `matm_notifications`, `matm_receipts`
- Meeting rooms and routing: `matm_meeting_rooms`, `matm_meeting_messages`, `matm_routing_decisions`, `matm_meeting_reads`
- Distributed sync: `matm_sync_devices`, `matm_sync_heads`, `matm_sync_revisions`, `matm_sync_receipts`
- Human review and promotion: `matm_review_queue`
- Retry safety and asynchronous processing: `matm_idempotency`, `matm_outbox_events`
- Quota and transparency: `matm_storage_ledger`, `matm_audit_log`

Runtime state today:

- MySQL/MariaDB: production backend. `/api/version` must report `storeBackend` as `mysql` or `mariadb` and `storeBackendVerified` as `true`.
- SQLite backend: default stdlib relational option for local verification of implemented MATM workflows. Its table set includes hierarchy and membership, hashed keys, agents, memory and revisions, wiki sources and documents, canonical external links and mentions, review, current messages and notifications, receipts, meeting rooms and routing, distributed sync, idempotency, outbox, quota ledger, and audit logs.
- File backend: local fallback for development and tests; it is not the production target.

Design rules:

- Store public-safe summaries instead of raw private payloads.
- Store token hashes, never raw API keys.
- Model `project -> workspace -> company`, and model accounts as many-to-many company memberships.
- Keep current messages separate from promoted durable memory.
- Model company, workspace, project, goal, and task meeting rooms as first-class durable objects, not as ad hoc current-message broadcasts or UI-only labels.
- Record review/promotion decisions before company, workspace, or project long-term memory is treated as authoritative.
- Use idempotency records for protected mutation retries.
- Use storage ledger entries to enforce the 200 MB free account quota.
- Store crawlable company/workspace/project wiki knowledge in database rows, not generated filesystem trees.
- Store each external URL once as a canonical workspace record and store every citation context as a separate mention. Incidental unreviewed mentions must not downgrade an explicit reviewed, quarantined, or rejected canonical state.
- Use device authority epochs, immutable sync revisions, monotonic server checkpoints, authoritative heads, tombstones, and redacted receipts for distributed sync. Do not use silent last-write-wins or claim rollback of arbitrary external effects.
- Reject task-level durable wiki trees. Tasks can have meeting rooms, but durable wiki knowledge must live at company, workspace, or project level.
- Ingest research reports one file at a time with reviewed title, description, keywords, source URI, category, project placement, and one-or-more taxonomy paths. Pair each wiki document with a compact MATM memory summary so agents can recall the right page without loading full reports into active context.
- Allow one knowledge document to appear in multiple contextual hierarchies without duplicating the report body. Hierarchy paths are part of the document contract because exact keyword search is insufficient for concepts such as prompt budgets, tokenization, prompt optimization, cost governance, and context management.
