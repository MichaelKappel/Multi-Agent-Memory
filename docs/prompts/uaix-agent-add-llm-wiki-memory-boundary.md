# Prompt For UAIX.org Agent: Add Documentation Site Plus Hosted Memory Endpoint Boundary

Target update URL: https://uaix.org/en-us/tools/ai-memory-package-wizard/#setup-llm-wiki

## Task

Update the UAIX LLM Wiki setup guidance and the AI Memory Package Wizard so the generated package model can explicitly represent a three-part memory boundary:

- Short-term/startup memory: active `.uai/` files.
- Public documentation site: a docs or GitHub companion site that explains the project and exposes public AI-readable discovery.
- Hosted mid-to-long-term memory endpoint: a live memory service or API that stores authenticated durable workspace memory.

## Concrete Example

Use MemoryEndpoints.com and MultiAgentMemory.com only as a generic implementation example, not as UAIX endorsement language:

- `.uai/` is the short-term and startup continuity layer.
- `MemoryEndpoints.com` is the hosted MATM mid-to-long-term memory endpoint.
- `MultiAgentMemory.com` is the public documentation and GitHub companion site.

## Requested Spec Addition

Add guidance to the LLM Wiki setup section that a project may have separate public documentation and hosted memory endpoint URLs. The long-term pointer ledger should be able to record both without retiring `.uai` startup memory.

Recommended generic fields for `.uai/long-term-memory.uai` pointer records:

- `stable_id`
- `path`
- `update_url`
- `label`
- `routing_summary`
- `authority_or_source`
- `review_status`
- `review_evidence`
- `truth_boundary`
- `documentation_site_url` when separate from the memory endpoint
- `hosted_memory_endpoint_url` when live durable memory is provided by an API or service

## Requested Wizard Addition

In the AI Memory Package Wizard LLM Wiki setup path, add optional inputs or generated output fields for:

- public documentation site URL
- hosted memory endpoint URL
- update URL for the spec or wizard setup path
- reminder that `.uai` remains active short-term/startup memory
- generated prompt block for agents asking them to update related docs, specs, or wizard outputs without claiming certification or automatic sync

## Safety And Claim Boundary

Keep the wording generic. Do not claim that UAIX endorses MemoryEndpoints.com, MultiAgentMemory.com, or any hosted memory endpoint. Do not imply automatic sync, automatic repository writes, hosted import validation, certification, endorsement, or hidden credential validation.

## Acceptance Criteria

- The setup-llm-wiki guidance says `.uai` stays active as startup continuity memory.
- The wizard can represent separate documentation-site and hosted-memory-endpoint URLs.
- The generated long-term pointer ledger can include an explicit update URL.
- The generated agent prompt keeps public documentation, hosted durable memory, and private credentials separate.
