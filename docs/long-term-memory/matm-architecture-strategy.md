# MATM Architecture Strategy

Purpose: durable strategy memory for MemoryEndpoints.com as a Multi-Agent Transactive Memory endpoint.

## Core Model

MemoryEndpoints.com should model MATM as a split-memory system:

- Hot startup memory: the full typed local `.uai` suite stays active always.
- Durable hosted memory: authenticated MemoryEndpoints.com MATM routes store mid-to-long-term workspace memory.
- Companion public docs: MultiAgentMemory.com explains the model and discovery boundary.
- Evidence layer: route verification, dogfood reports, redacted receipts, readiness reports, and deployment reports prove claims.

The transactive-memory dimensions to preserve are specialization, credibility, and coordination:

- Specialization: agents, namespaces, stores, and routes should have clear responsibility.
- Credibility: each memory event needs provenance, confidence, review status, and authority boundary.
- Coordination: current messages, acknowledgements, receipts, idempotency, and review queues keep agents synchronized.

## Hierarchical And Crawlable Memory

- Use the typed `.uai` suite for compact current-state memory and startup continuity.
- Do not create a catch-all `.uai` file such as `short-term-memory.uai`, `active-memory.uai`, or `current-state.uai`; every startup-loaded typed `.uai` file is active memory.
- Use `docs/long-term-memory` for reviewed durable strategy and release memory.
- Use MemoryEndpoints.com protected MATM routes for authenticated workspace memory and current-message coordination.
- Keep pointer ledgers link-rich and context-rich: stable id, path, routing summary, authority/source, review status, evidence, and truth boundary.
- Avoid monolithic memory dumps. Store summaries, pointers, and reviewed targets that can be loaded by need.

## Timestamp-Free Memory Strategy

Default ranking and maintenance should not rely on timestamps as a shortcut for truth or relevance.

Use these signals first:

- Semantic fit to the current task.
- Provenance and authority.
- Review status and confidence.
- Utility from previous successful use.
- Graph support and relationship centrality.
- Novelty, contradiction checks, and duplicate suppression.
- Drift detection and supersession links.

Dates and times remain useful for audits, legal records, deployment chronology, and explicitly temporal questions. They should not be the default relevance signal for MATM memory selection.

## Memory Write Pipeline

Treat memory writes as a pipeline:

1. Extract candidate memory units from user requests, reports, code changes, verification output, or live dogfood.
2. Classify scope as local `.uai`, durable docs, hosted MATM, or rejected/private.
3. Redact secrets and private payload bodies before persistence.
4. Deduplicate against existing active memory and durable docs.
5. Attach provenance, authority, confidence, and review status.
6. Promote public-safe current facts into `.uai`.
7. Promote durable strategy into `docs/long-term-memory`.
8. Submit authenticated MATM updates to `https://memoryendpoints.com/api/matm/memory-events/submit` when credentials and connectivity exist.
9. Record proof of use in `.uai/intake-outcome-ledger.uai` or progress reports.

## Conflict And Supersession

- Prefer semantic supersession over last-write-wins.
- Preserve rejected or retired claims as statused records when they explain why the current target changed.
- Use content hashes, stable ids, and review evidence to avoid duplicate inflation.
- Access control must run before ranking, not after retrieval.
- Shared memory poisoning is a first-class threat; memory writes need provenance, validation status, scope constraints, and redacted audit trails.

## Evaluation Targets

MATM readiness should be judged by:

- Retrieval precision and recall.
- Update correctness and stale-memory suppression.
- Contradiction rate.
- Inter-agent coherence.
- Access-policy correctness.
- Secret-redaction correctness.
- Dogfood workflow success.
- Storage footprint, route latency, and package/deploy safety.
- Robustness under semantic drift and agent handoff.
