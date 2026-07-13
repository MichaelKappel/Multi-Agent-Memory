# MATM Architecture Strategy

Purpose: checked-in strategy history for MemoryEndpoints.com. Current implementation details live in [System Architecture](../system-architecture.md), and reviewed durable strategy lives in protected hosted knowledge and memory.

## Core Model

MemoryEndpoints.com should model MATM as a split-memory system:

- Hot startup memory: the full typed local `.uai` suite stays active always.
- Durable hosted memory: authenticated MemoryEndpoints.com MATM routes store mid-to-long-term workspace memory.
- Companion public docs: MultiAgentMemory.com explains the model and discovery boundary.
- Evidence layer: exact-SHA route verification, authenticated dogfood, fail-closed agent audit access, seven-day human-only history, redacted receipts, MySQL verification, companion verification, and deployment reports bind claims.

The transactive-memory dimensions to preserve are specialization, credibility, and coordination:

- Specialization: agents, namespaces, stores, and routes should have clear responsibility.
- Credibility: each memory event needs provenance, confidence, review status, and authority boundary.
- Coordination: company/workspace/project/goal/task meeting rooms, structured routing, current messages, acknowledgements, receipts, idempotency, and review queues keep agents synchronized.

## Hierarchical And Crawlable Memory

- Use the typed `.uai` suite for compact operational memory and startup continuity.
- Do not create `.uai` files named `short-term-memory.uai`, `active-memory.uai`, `current-state.uai`, `project-state.uai`, `working-state.uai`, or equivalent under any purpose or interpretation; every startup-loaded typed `.uai` file is active memory.
- Use hosted MemoryEndpoints workspace memory and company/workspace/project wiki trees for reviewed durable strategy and release memory; keep `docs/long-term-memory` only as migration and decision history.
- Use MemoryEndpoints.com protected MATM routes for authenticated workspace memory, meeting-room coordination, current-message attention, reviewed wiki retrieval, and distributed sync.
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
2. Classify scope as typed startup `.uai`, protected company/workspace/project wiki, hosted MATM memory, transient coordination, or rejected/private.
3. Redact secrets and private payload bodies before persistence.
4. Deduplicate against existing active memory and protected hosted knowledge.
5. Attach provenance, authority, confidence, and review status.
6. Put only cold-start continuity, constraints, and semantic pointers into the appropriate typed `.uai` file; do not use shared `.uai` as a turn-by-turn scratchpad.
7. Promote durable strategy into the narrowest protected company/workspace/project wiki scope and compact hosted memory.
8. Submit authenticated MATM updates to `https://memoryendpoints.com/api/matm/memory-events/submit` when credentials and connectivity exist.
9. Record concise startup pointers in `.uai` and point-in-time verification under ignored `var/reports/`.

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
