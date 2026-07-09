# Storage Backends

MemoryEndpoints has local file and SQLite modes plus a production MySQL/MariaDB mode.

## File Backend

Default:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='file'
```

The file backend stores MATM state in JSON at `var/matm_store.json` unless `MEMORYENDPOINTS_STORE_PATH` overrides the path.

## SQLite Backend

Stdlib database-backed mode:

```powershell
$env:MEMORYENDPOINTS_STORE_BACKEND='sqlite'
$env:MEMORYENDPOINTS_SQLITE_PATH='E:\MemoryEndpoints.com\var\matm_store.sqlite3'
```

The SQLite backend stores implemented MATM workflow state in relational tables using Python's standard `sqlite3` module. It creates separate tables for accounts, companies, account-company memberships, workspaces, projects, API keys, agents, memory records, memory revisions, memory tags, crawl sources, search documents, review queue entries, current messages, notifications, receipts, idempotency records, outbox events, storage ledger entries, and audit logs.

The SQLite backend no longer relies on a single JSON blob table for the active tested workflows. It preserves the same route-level behavior as the file backend and uses SQLite `TRUNCATE` journal mode for constrained shared-host filesystems. SQLite is useful for local verification, but it is not the production-completion backend.

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

The canonical MySQL/MariaDB relational schema is in `docs/database-schema-canonical.sql`. The app initializes missing tables on connection. `/api/version` must report `storeBackend` as `mysql` or `mariadb` and `storeBackendVerified` as `true` before the site can be claimed to be using real MySQL.
