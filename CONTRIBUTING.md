# Contributing

Contributions should improve MemoryEndpoints as a clear, safe, AI-ready MATM reference.

Rules:

- Do not commit secrets, raw private memory payloads, database passwords, FTP credentials, or local deployment files.
- Keep runtime dependencies out unless the human maintainer explicitly approves them.
- Preserve attribution and license notices.
- Use the existing route, storage, confirmation, and safe-no-op patterns; do not add one-off bypasses or a second source of truth.
- This project has not launched. Do not add compatibility shims, legacy aliases, dual-write paths, or migration debt unless the maintainer explicitly requests compatibility.
- Add focused integration tests for route, storage, memory, security, sync, documentation, or discovery behavior changes.
- When adding or changing a route, update `memoryendpoints.site_data.ROUTE_TABLE`, `docs/route-inventory.md`, `docs/api-contract.md`, and the MultiAgentMemory.com API reference in the same change.
- Write generated verifier output under ignored `var/reports/`; do not treat tracked point-in-time reports as proof of a later commit.
- Keep public claims bounded by evidence.

Required review evidence:

- Full unit and integration suite.
- WSGI and companion-site verifiers.
- `.uai`, repository-boundary, package, secret, documentation, and diff checks.
- Exact-SHA live deployment, MySQL verification, and authenticated dogfood when the change affects the production contract.
