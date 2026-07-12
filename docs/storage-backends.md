# Storage Backends

MemoryEndpoints has local file and SQLite modes plus a production MySQL/MariaDB mode.

## File Backend

Explicit development fallback:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='file'
```

The file backend stores MATM state in JSON at `var/matm_store.json` unless `MEMORYENDPOINTS_STORE_PATH` overrides the path.

## SQLite Backend

Default local stdlib database-backed mode:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='sqlite'
$env:MEMORYENDPOINTS_SQLITE_PATH='.\var\matm_store.sqlite3'
```

The SQLite backend stores implemented MATM workflow state in relational tables using Python's standard `sqlite3` module. It creates separate tables for accounts, companies, account-company memberships, workspaces, projects, API keys, agents, virtual UAIX packages and immutable record revisions, hash-only local `.uai` collaboration heads and edit claims, memory records, memory revisions, memory tags, crawl sources, search documents, canonical external links, external-link mentions, review queue entries, current messages, notifications, receipts, meeting rooms, meeting messages, routing decisions, meeting read cursors, sync devices, sync heads, sync revisions, sync receipts, idempotency records, outbox events, storage ledger entries, and audit logs.

The SQLite backend no longer relies on a single JSON blob table for the active tested workflows. It preserves the same route-level behavior as the file backend and uses SQLite `TRUNCATE` journal mode for constrained shared-host filesystems. SQLite is useful for local verification, but it is not the production-completion backend.

The database-backed knowledge wiki uses `matm_crawl_sources` and `matm_search_documents` for full crawlable report context. `matm_external_links` stores canonical URL and search properties while `matm_external_link_mentions` stores per-document citation context. The filesystem is only an intake or evidence source; it is not the durable wiki tree. A report should be ingested one file at a time with reviewed title, description, keywords, taxonomy paths, scope, category, source URI, project placement, and a separate compact MATM memory summary for recall. Multiple taxonomy paths are normal; they let one canonical document appear in several contextual hierarchies without duplicating stored content.

The full virtual UAIX package is a narrow exception for an accountless browser
AI that has no durable local filesystem. File, SQLite, and MySQL backends expose
the same package/record/startup contract, but production requires MySQL. Normal
filesystem agents use the local collaboration overlay instead: MemoryEndpoints
stores path hashes and claims, never their `.uai` bodies. Integration tests run
the virtual package through file and SQLite parity and run the transactional
claim/conflict path through SQLite; live MySQL verification remains required
after deployment.

SQLite databases, journals, JSON stores, logs, caches, deployment packages, raw Agent File Handoff bucket contents, and credential handoff files are local state. They are ignored by Git and excluded by `scripts/package_memoryendpoints.py`.

## MySQL / MariaDB

Production mode:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='mysql'
$env:MEMORYENDPOINTS_MYSQL_HOST='<host>'
$env:MEMORYENDPOINTS_MYSQL_PORT='3306'
$env:MEMORYENDPOINTS_MYSQL_DATABASE='<database>'
$env:MEMORYENDPOINTS_MYSQL_USER='<user>'
$env:MEMORYENDPOINTS_MYSQL_PASSWORD='<password>'
```

`MEMORYENDPOINTS_MYSQL_URL` or `DATABASE_URL` may also be used with a `mysql://` or `mariadb://` URL. Secrets must stay outside Git.

If Passenger/cPanel cannot expose environment variables reliably, the runtime can read a JSON secret file from the path in `MEMORYENDPOINTS_MYSQL_CONFIG_PATH`, or from `.local-secrets/mysql.json` by default. When that file exists, it is the authoritative MySQL credential source over URL and individual environment variables:

```json
{
  "host": "<host>",
  "port": 3306,
  "database": "<database>",
  "user": "<user>",
  "password": "<password>"
}
```

The `.local-secrets/` directory is ignored by Git and excluded from the deployment package. Create or upload that file directly on the host outside source control. When this file exists and `MEMORYENDPOINTS_STORE_BACKEND` is not explicitly set, the runtime treats it as the host-side selection for the MySQL backend.

The canonical MySQL/MariaDB relational schema is in `docs/database-schema-canonical.sql`. The app initializes missing tables on connection. `/api/version` must report `storeBackend` as `mysql` or `mariadb` and `storeBackendVerified` as `true` before the site can be claimed to be using real MySQL.

Local ingestion tools read JSON secret/config files with UTF-8 BOM tolerance so Windows-authored `.local-secrets/*.json` files work without manual cleanup. Secret values still stay outside source control and must not be echoed in logs or reports.
