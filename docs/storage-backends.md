# Storage Backends

MemoryEndpoints has two live stdlib storage modes.

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

The SQLite backend stores implemented MATM workflow state in relational tables using Python's standard `sqlite3` module. It creates separate tables for workspaces, API keys, agents, memory records, memory tags, review queue entries, current messages, notifications, receipts, idempotency records, outbox events, storage ledger entries, and audit logs.

The SQLite backend no longer relies on a single JSON blob table for the active tested workflows. It preserves the same route-level behavior as the file backend, uses SQLite `TRUNCATE` journal mode for compatibility with constrained shared-host filesystems, and requires no third-party runtime packages.

SQLite databases, journals, JSON stores, logs, caches, deployment packages, raw Agent File Handoff bucket contents, and credential handoff files are local state. They are ignored by Git and excluded by `scripts/package_memoryendpoints.py`.

## MySQL / MariaDB

MySQL and MariaDB remain adapter-gated. Python's standard library does not include a MySQL client, and this project must not add third-party runtime dependencies without explicit maintainer approval.

The canonical MySQL/MariaDB-oriented relational schema is in `docs/database-schema-canonical.sql`; the SQLite implementation mirrors the same MATM responsibilities with SQLite-compatible column types and indexes where the current stdlib runtime supports them. The table purpose guide is in `docs/database-structure.md`.
