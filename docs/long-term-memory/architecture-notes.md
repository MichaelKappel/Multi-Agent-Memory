# Architecture Notes

The first implementation uses a Python stdlib WSGI app with a JSON file store by default.

The app also supports a stdlib SQLite backend by setting `MEMORYENDPOINTS_STORE_BACKEND=sqlite`. SQLite gives MemoryEndpoints a relational database-backed durable mode for the implemented MATM workflows without adding third-party runtime dependencies.

The MySQL/MariaDB production adapter exists through `memoryendpoints.storage.MySQLStore` and requires a configured Python MySQL driver plus `MEMORYENDPOINTS_STORE_BACKEND=mysql` or `mariadb`. The live site is not using real MySQL unless `/api/version` reports `storeBackend` as `mysql` or `mariadb`.

The canonical database structure is `docs/database-schema-canonical.sql`. It separates account hierarchy, durable memory, crawl/search records, current-message delivery, receipts, review promotion, idempotency, outbox events, quota ledger, and audit log.

Long-term memory starts in `docs/long-term-memory` and can later be promoted into hosted MemoryEndpoints MATM storage once deployment and authority gates are proven.

The local `.uai` folder remains active even after hosted MATM is verified. `.uai/totem.uai` is the invariant record: hosted MATM augments durable memory, but it does not retire local startup continuity or offline recovery memory.
