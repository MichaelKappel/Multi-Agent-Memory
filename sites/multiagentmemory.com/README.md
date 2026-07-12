# MultiAgentMemory.com

MultiAgentMemory.com is the GitHub companion documentation site for the MemoryEndpoints.com MATM endpoint project.

Primary links:

- Live documentation site: https://multiagentmemory.com
- Source repository: https://github.com/MichaelKappel/Multi-Agent-Memory
- Hosted endpoint site: https://memoryendpoints.com
- Detailed system guide: https://multiagentmemory.com/docs/how-it-works.html
- API and data reference: https://multiagentmemory.com/docs/api-reference.html
- Memory boundary: https://multiagentmemory.com/docs/memory-boundary.html

Memory boundary:

- Active startup memory: the full repository `.uai/` suite.
- Accountless-browser exception: complete protected virtual UAIX records bound to a registered agent and workspace key when no durable local filesystem exists.
- Concurrent local-agent overlay: project/path hashes and bounded edit claims; local `.uai` bodies remain local.
- Mid-to-long-term hosted memory: MemoryEndpoints.com protected MATM routes.
- Public documentation and GitHub-facing explanation: MultiAgentMemory.com.

How it works:

- `memoryendpoints/` contains the pure stdlib WSGI MATM endpoint runtime.
- `sites/multiagentmemory.com/` contains the static GitHub companion documentation site.
- `scripts/` contains verification, packaging, secret scanning, dogfood, readiness, and deploy helpers.
- `tests/` covers public discovery, virtual UAIX startup and revision behavior, hash-only local edit claims, protected MATM workflows, hierarchy navigation, contextual knowledge search, external-link citations, curated web search, meeting-room routing, current-message delivery, distributed-sync conflicts, memory firewall behavior, idempotency, review decisions, audit readback, documentation freshness, and relational-backend parity.
- `.uai/` remains active startup memory always; hosted MATM augments durable memory but does not replace local continuity.
- MemoryEndpoints.com database records are the durable knowledge source of truth for reviewed company, workspace, and project wiki pages. Repository docs are not a second memory hierarchy.
- MemoryEndpoints.com protected routes handle memory submit/search, hierarchy crawl, semantic page search, first-class external citations, curated web search, meeting-room routing, current-message coordination, conflict-safe distributed sync, notification acknowledgements, review decisions, receipts, and protected audit-log readback.
- The checked-in route table, GitHub route inventory and API contract, and companion API reference are compared by tests. Tracked reports remain point-in-time evidence rather than proof of a later commit.

The documentation model follows the UAIX AI Memory Package Wizard MemoryEndpoints.com MATM setup boundary:

- Keep the full `.uai` suite active as compact startup continuity memory.
- Use `.uai/long-term-memory.uai` as a semantic pointer ledger.
- Use a configured MATM update URL for reviewed medium and long-term memory.
- Use MemoryEndpoints.com as a suggested MATM endpoint example.
- Use the full virtual package only for an accountless browser AI with no durable local filesystem; ordinary local agents coordinate with hashes and claims without uploading file bodies.
- Do not claim certification, endorsement, automatic sync, or hidden runtime authority.

Setup references:

- UAIX AI memory: https://uaix.org/en-us/ai-memory/
- UAIX package format: https://uaix.org/en-us/ai-memory/uaix-package-format/
- UAIX setup option: https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM-MemoryEndpoints
- MemoryEndpoints.com inbound/home: https://memoryendpoints.com

Setup mode:

- MemoryEndpoints.com MATM
- Mode id: setup-MATM-MemoryEndpoints

Inbound link rule: UAIX may use setup-option fragments because it has multiple wizard modes. MemoryEndpoints.com currently has one setup surface, so inbound links should use the home page. Future MemoryEndpoints setup URLs should be clean readable routes.
