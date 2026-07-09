# Enterprise Engineering Best Practices

Purpose: durable public-safe best-practice memory distilled from local strategy intake.

## Python Engineering

- Keep runtime dependencies conservative and explicit. For MemoryEndpoints.com production, the human-approved exception is the MySQL/MariaDB driver needed for the required production database backend.
- Prefer small modules with explicit contracts over framework-shaped indirection. The app should keep route handling, storage, memory policy, packaging, deployment, and verification responsibilities separated.
- Make behavior deterministic where agents or deploy tooling rely on it: explicit environment variables, stable JSON shapes, idempotency keys, redacted reports, repeatable package manifests, and command-line verification entry points.
- Use typed boundaries even when no external type checker is required: predictable dictionaries, documented payload fields, schema files, and tests that enforce response shape.
- Keep security boundaries in the implementation, not only in docs: access control before data lookup, redaction before reporting, hash-only credential handling, safe no-op responses for unsupported operations, and no raw secret echo.

## Testing And Verification

- Keep the local test suite fast, hermetic, and runnable with `python -m unittest discover -s tests`.
- Preserve layered verification: unit/integration tests, WSGI route verification, live public-route verification, package verification, `.uai` audit, secret scan, enterprise readiness audit, and deployment reports.
- Separate local proof from live proof. Local WSGI checks prove current code behavior; live public-route and live dogfood checks prove the deployed surface; `/api/version` SHA verification proves whether that deployed surface is the expected Git commit.
- Treat dogfooding as an integration test, not as marketing evidence. It must exercise workspace creation, agent registration, memory submit/search, current message, acknowledgement, receipt readback, protected audit-log readback, redaction, and `.uai` progress behavior.
- Track optional route gaps separately from required workflow failures. An optional live route missing from the deployed site should not erase a verified required workflow, but it should remain visible as deploy drift.

## MySQL And Database Operations

- Treat MySQL/MariaDB as the production-completion backend, not a future optional adapter. `/api/version` must verify `storeBackend` as `mysql` or `mariadb` and `storeBackendVerified` as `true`.
- Continue supporting file storage and SQLite relational MATM tables as active local-development backends, but do not let them satisfy production readiness.
- Require stable primary keys, explicit indexes, migration-driven schema changes, idempotency tables, quota ledgers, audit trails, and review queues in durable storage designs.
- For future enterprise MySQL deployment planning, prefer an LTS track, InnoDB, explicit backup and point-in-time recovery drills, TLS, least-privilege roles, audit logging, and observability before claiming production readiness.
- Do not treat read replicas as automatic HA unless the chosen managed service explicitly supports that failover mode. Record RPO/RTO assumptions before selecting topology.

## Governance

- Promote facts into active memory only after they are represented in code, docs, tests, reports, or `.uai` records.
- Keep raw intake reports local-only unless a human explicitly approves publication.
- Record each intake distribution in `.uai/intake-outcome-ledger.uai`.
