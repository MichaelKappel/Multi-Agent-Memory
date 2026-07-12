# Architecture Notes

This file is a compact historical entry point. The current detailed source is [System Architecture](../system-architecture.md).

The implementation uses a Python standard-library WSGI application. SQLite is the default local relational backend; file storage is an explicit development/test fallback. The MySQL/MariaDB production adapter requires a host-provided compatible Python driver and is considered active only when `/api/version` reports a verified MySQL/MariaDB backend.

The canonical schema at `docs/database-schema-canonical.sql` separates tenant hierarchy, key hashes, durable memory and revisions, wiki sources and documents, canonical external links and citation mentions, meeting rooms and routing decisions, current-message notifications, distributed-sync authority and revisions, review state, idempotency, receipts, quota, and redacted audit evidence.

Protected knowledge and memory live in database records. Files under `docs/long-term-memory/` preserve migration and decision history; they are not the protected workspace search source and do not replace one-source-at-a-time database ingestion.

The local `.uai` suite remains active after hosted MATM is verified. Hosted MATM augments durable recall but cannot retire local startup continuity or offline recovery memory.
