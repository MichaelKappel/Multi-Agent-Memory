# Release Verification Contract

MemoryEndpoints releases are accepted by exact-revision evidence, not by a dated prose claim or a tracked generated report.

## Required Gates

- GitHub `main` and the local checked head identify the same full source SHA.
- The package report records that SHA, zero dirty source paths, excluded secrets/runtime state, file count, content hash, and package hash.
- The explicit-FTPS dry run and connection check pass before upload.
- The live upload requests Passenger restart and reports the package file count as uploaded.
- [`/api/version`](https://memoryendpoints.com/api/version) reports the expected full source SHA and a verified MySQL/MariaDB backend.
- The live MemoryEndpoints route verifier passes its public contract set with no secret or local-path leak findings.
- Authenticated live dogfood passes workspace setup, agent registration, memory submit/search/review, meeting coordination, current-message delivery and acknowledgement, receipts, and audit readback.
- The live [MultiAgentMemory.com](https://multiagentmemory.com) verifier passes every required HTML and discovery artifact.
- Unit and integration tests, `.uai` audit, repository-boundary audit, documentation-freshness test, secret scan, package check, and diff check pass from the same checked revision.

## Current Evidence Sources

- Runtime provenance: [`/api/version`](https://memoryendpoints.com/api/version)
- Capability state: [`/api/matm/live-capability-matrix`](https://memoryendpoints.com/api/matm/live-capability-matrix)
- Full route map: [`/api/matm/route-inventory`](https://memoryendpoints.com/api/matm/route-inventory)
- Distributed-sync contract: [`/api/matm/sync/capabilities`](https://memoryendpoints.com/api/matm/sync/capabilities)
- Bounded route schema: [`/api/matm/openapi.json`](https://memoryendpoints.com/api/matm/openapi.json)
- Readiness boundary: [`/api/matm/readiness-result`](https://memoryendpoints.com/api/matm/readiness-result)
- Human documentation: [MultiAgentMemory.com](https://multiagentmemory.com)
- Complete companion route guide: [API and data reference](https://multiagentmemory.com/docs/api-reference.html)

Fresh verifier output is written under ignored `var/reports/`. Existing files under `docs/reports/` are historical point-in-time snapshots; they do not prove a later commit and must not override exact-SHA live evidence.

GitHub Actions remains optional by operator direction. It does not replace local tests, exact-SHA deployment proof, live MySQL verification, or authenticated dogfood.
