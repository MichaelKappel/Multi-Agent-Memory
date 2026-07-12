# API Contract Summary

The complete current contract is [docs/api-contract.md](../api-contract.md); the complete deployed route list is returned by `/api/matm/route-inventory`.

Protected mutation routes support idempotency keys except for free-account setup, which returns a raw key once and does not store raw key material for replay.

Search returns hosted workspace memory from MemoryEndpoints storage. Files under `docs/long-term-memory` are migration seeds and source-controlled evidence, not the protected search source.

Protected routes cover tenant hierarchy, project records, registered-agent virtual UAIX packages for the accountless-browser exception, hash-only local `.uai` edit coordination, company/workspace/project wiki trees, lifecycle-aware documents, canonical external links and citation mentions, curated internet search, memory firewall and review, meeting-room routing, current-message delivery, redacted receipts and audits, and conflict-safe distributed sync.

Important mutations confirm persistence through their read model. A normal success response is not returned when required search, tree, transcript, inbox, receipt, head, or audit readback fails.

Virtual active-record writes are date-free, structurally validated, public-safe,
revision-checked, and returned in deterministic startup order. Local
collaboration claims never store the local file body and never claim automatic
merge behavior.
