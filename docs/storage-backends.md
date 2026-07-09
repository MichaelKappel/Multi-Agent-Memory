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

The SQLite backend stores the same MATM state in a local SQLite database using Python's standard `sqlite3` module. It uses SQLite `TRUNCATE` journal mode for compatibility with constrained shared-host filesystems, preserves the same API behavior as the file backend, and requires no third-party runtime packages.

SQLite databases, journals, JSON stores, logs, caches, deployment packages, and credential handoff files are runtime state. They are ignored by Git and excluded by `scripts/package_memoryendpoints.py`.

## MySQL / MariaDB

MySQL and MariaDB remain adapter-gated. Python's standard library does not include a MySQL client, and this project must not add third-party runtime dependencies without explicit maintainer approval.

The canonical relational schema is in `docs/database-schema-canonical.sql`; the table purpose guide is in `docs/database-structure.md`.
