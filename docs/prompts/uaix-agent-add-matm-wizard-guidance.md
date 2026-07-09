# Prompt For UAIX.org Agent: Add MATM Setup Guidance And Update URLs

## Target UAIX Wizard URLs To Add

- `https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-MATM`
- `https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-file-handoff-MATM`

## Task

Update the UAIX AI Memory Package Wizard, the related `.uai` memory specification guidance, and any agent-facing setup guidance so MATM is a first-class durable-memory option beside the existing local `.uai`, Agent File Handoff, and LLM Wiki paths.

The new guidance should explain how to set up UAIX `.uai` memory with a MATM system:

- `.uai/` remains the hot short-term and startup continuity layer.
- MATM is the authenticated mid-term and long-term multi-agent memory layer.
- Agent File Handoff can be paired with MATM when active dropped-file intake must be reviewed, acted on, and preserved into durable memory.
- A generated `.uai/long-term-memory.uai` pointer can name the MATM update URL so agents know exactly where safe memory updates should be submitted.
- MemoryEndpoints.com can be listed as a suggested/example MATM endpoint implementation, without implying UAIX certification or endorsement.

## Requested Wizard Additions

Add two setup modes to the wizard routing and embedded AI digest:

- `#setup-MATM`: configure `.uai` startup memory plus a hosted MATM durable-memory endpoint.
- `#setup-file-handoff-MATM`: configure `.uai` startup memory, Agent File Handoff active intake buckets, and a hosted MATM durable-memory endpoint.

For both setup modes, add wizard fields for:

- MATM endpoint base URL.
- MATM memory update URL.
- MATM memory search URL.
- Current-message read URL.
- Notification acknowledgement URL.
- Optional redacted receipt URL.
- Public documentation site URL, when separate from the endpoint.
- Human-readable authority and truth-boundary notes.
- Secret-handling warning that credentials must not be written into `.uai`, public docs, generated packages, logs, or reports.

## Requested `.uai` Spec Guidance

Add or document a pointer-record shape for MATM-backed projects. Recommended public-safe fields:

- `stable_id`
- `path`
- `update_url`
- `search_url`
- `current_message_url`
- `acknowledgement_url`
- `receipt_url`
- `label`
- `routing_summary`
- `authority_or_source`
- `review_status`
- `review_evidence`
- `truth_boundary`
- `documentation_site_url`
- `credential_storage_boundary`

The `update_url` must identify the MATM route where an authorized agent can submit safe memory updates. It must not point at the UAIX wizard page unless the wizard page itself is the thing being updated.

## Suggested Example

Use this only as an example implementation, not as endorsement language:

- Short-term/startup memory: repository `.uai/` files.
- MATM durable-memory endpoint: `https://memoryendpoints.com`.
- MATM update URL example: `https://memoryendpoints.com/api/matm/memory-events/submit`.
- MATM search URL example: `https://memoryendpoints.com/api/matm/search`.
- Current-message URL example: `https://memoryendpoints.com/api/matm/current-message`.
- Notification acknowledgement URL example: `https://memoryendpoints.com/api/matm/notifications/ack`.
- Redacted receipt URL example: `https://memoryendpoints.com/api/matm/receipts`.
- Companion documentation site: MultiAgentMemory.com.

## Agent Guidance To Generate

The wizard should generate a short agent instruction block:

1. Load `.uai/` first for startup continuity and current constraints.
2. Use MATM only through the configured authenticated routes.
3. Submit only public-safe, reviewed, non-secret updates to the MATM update URL.
4. Keep raw credentials outside `.uai`, generated packages, public docs, reports, and logs.
5. Use Agent File Handoff buckets only when the selected setup mode includes File Handoff, and record disposition/proof-of-use before claiming intake completion.
6. Do not claim UAIX certification, endorsement, automatic sync, automatic repository writes, hosted import validation, or hidden credential validation.

## Acceptance Criteria

- The wizard exposes `#setup-MATM`.
- The wizard exposes `#setup-file-handoff-MATM`.
- The `.uai` spec documents `update_url` as a MATM memory update target for MATM-backed packages.
- The generated package keeps `.uai` active as short-term/startup memory.
- The generated package can name MemoryEndpoints.com as an optional suggested MATM endpoint example.
- The generated package keeps credentials out of `.uai`, public docs, logs, reports, and exported packages.
- The generated language distinguishes UAIX guidance from third-party MATM endpoint endorsement.
