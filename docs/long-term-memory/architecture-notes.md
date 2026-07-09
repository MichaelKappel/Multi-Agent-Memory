# Architecture Notes

The first implementation uses a Python stdlib WSGI app with a JSON file store by default.

The app also supports a stdlib SQLite backend by setting `MEMORYENDPOINTS_STORE_BACKEND=sqlite`. SQLite gives MemoryEndpoints a database-backed durable mode without adding third-party runtime dependencies.

The MySQL/MariaDB production adapter is still gated because the Python standard library does not include a MySQL client. A future adapter may use an approved driver, host-provided command boundary, or a reviewed pure-Python protocol adapter after explicit review.

The canonical database structure is `docs/database-schema-canonical.sql`. It separates account hierarchy, durable memory, crawl/search records, current-message delivery, receipts, review promotion, idempotency, outbox events, quota ledger, and audit log.

Long-term memory starts in `docs/long-term-memory` and can later be promoted into hosted MemoryEndpoints MATM storage once deployment and authority gates are proven.
