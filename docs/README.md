# Documentation

This folder contains checked-in engineering documentation for the Multi-Agent Memory repository. Durable product knowledge belongs in protected MemoryEndpoints.com company/workspace/project database trees, not in a second filesystem wiki.

## Core Docs

- [API contract](api-contract.md)
- [System architecture](system-architecture.md)
- [Route inventory](route-inventory.md)
- [Storage backends](storage-backends.md)
- [Database structure](database-structure.md)
- [Repository structure](repository-structure.md)
- [Verification](verification.md)
- [Deployment](deployment.md)

## Evidence Model

Use evidence in this order:

1. Checked-in code and tests define what a Git revision implements.
2. [`/api/version`](https://memoryendpoints.com/api/version) identifies the exact deployed source SHA and production storage backend.
3. The live [route inventory](https://memoryendpoints.com/api/matm/route-inventory), [capability matrix](https://memoryendpoints.com/api/matm/live-capability-matrix), [UAIX active-memory contract](https://memoryendpoints.com/api/matm/uai-memory/contract), [sync capabilities](https://memoryendpoints.com/api/matm/sync/capabilities), and [readiness result](https://memoryendpoints.com/api/matm/readiness-result) describe the deployed public contract.
4. Fresh local and live verifier output under ignored `var/reports/` proves a point-in-time check without making generated artifacts part of the documentation source of truth.

The existing `docs/reports/` files are historical point-in-time snapshots. They can explain earlier decisions but are not current-release proof and must not override code, tests, or exact-SHA live evidence.

## Historical Strategy Notes

- [Strategy memory index](long-term-memory/strategy-index.md)
- [Enterprise engineering best practices](long-term-memory/enterprise-engineering-best-practices.md)
- [MATM architecture strategy](long-term-memory/matm-architecture-strategy.md)
- [System targets](long-term-memory/system-targets.md)
- [Release verification summary](long-term-memory/release-verification-summary.md)
- [Architecture notes](long-term-memory/architecture-notes.md)
- [Project charter](long-term-memory/project-charter.md)

These checked-in notes are migration and design history. Current reviewed strategy is promoted one source at a time into protected MemoryEndpoints.com knowledge and memory records.
