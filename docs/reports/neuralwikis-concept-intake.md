# NeuralWikis Concept Intake Report

Generated: 2026-07-09

## Purpose

This report records the public-safe concepts inspected from `E:\NeuralWikis.com` and translated into MemoryEndpoints.com requirements. It does not copy NeuralWikis public wiki pages, branding, marketing claims, private memory bodies, credentials, or generated public content.

## Source Boundary

Inspected as concept evidence:

- `models/agent_exchange/memory_firewall.py`
- `models/agent_exchange/contracts.py`
- `models/agent_exchange/schemas.py`
- `docs/source-intake-review-queue-v1.md`
- `docs/source-intake-promotion-workflow-v1.md`
- `reports/uai-emergency-reconnect-refresh-matm-core-workflows-local-20260629-105442/summary.md`
- `reports/uai-emergency-reconnect-refresh-matm-security-tenancy-local-20260629-110814/summary.md`
- `reports/uai-emergency-reconnect-refresh-matm-packet-adoption-lifecycle-20260629-112329/summary.md`
- `reports/uai-emergency-reconnect-refresh-memory-lifecycle-e2e-20260630-101815/summary.md`
- `reports/uai-emergency-reconnect-refresh-private-memory-success/summary.md`
- `memory/long-term/neurowikis-agent-ui-dogfood-intake/source-reports/Current-Message and Acknowledgement Workflow.md`

Excluded from MemoryEndpoints.com:

- Public wiki article bodies.
- NeuralWikis or NeuroWikis branding surfaces.
- Private source bodies.
- Credentials, tokens, private keys, deployment handoff values, and local runtime data.
- Public claims that are not independently true for MemoryEndpoints.com.

## Concepts Adopted

- Local `.uai` memory must stay active until durable memory is proven, and for MemoryEndpoints it stays active always as the totem invariant.
- Memory write paths need a deterministic memory firewall before persistence.
- Risky or secret-like memory belongs in review/quarantine state, not trusted active search by default.
- Review and promotion decisions must be protected, idempotent, auditable, and public-safe.
- Current-message workflows need mandatory `required_response` and `viewed_acknowledgement` states, with no vague optional wording.
- Dogfood evidence must include readback proof, acknowledgement proof, receipt proof, and redaction proof.
- Reports should state what was verified and what was not verified instead of implying completion.

## MemoryEndpoints Implementation Changes

- Added `.uai/totem.uai` and normalized all active `.uai` files with purpose, verification status, scope, update route, source of truth, next actions, and secret boundaries without embedding dates.
- Added `memoryendpoints/security.py` for deterministic redaction and memory firewall evaluation.
- Extended memory events with typed-memory fields, confidence, promotion state, review status, revision, body hash, and firewall summary.
- Added review queue storage and protected routes:
  - `GET /api/matm/review-queue`
  - `POST /api/matm/review-queue/decide`
- Added local WSGI dogfood runner at `scripts/dogfood_memoryendpoints.py`.
- Added redacted dogfood evidence report at `docs/reports/dogfood-memory-run.json`.

## Truth Boundary

This is concept intake, not content migration. MemoryEndpoints.com remains its own product and must continue to prove its own implementation, deployment, tests, packaging, dogfooding, and live route state.
