# Security

Report security issues privately to the project maintainer.

Do not open public issues containing:

- API keys
- database credentials
- FTP credentials
- raw private memory
- raw user secrets
- exploit payloads with live credentials

## Security Boundary

- Public routes expose product documentation and redacted evidence only. The public `/knowledge` route is an empty authentication shell.
- Protected routes require a workspace bearer key and constrain every read/write to the authenticated workspace.
- Workspace keys are returned once during setup and stored only as hashes.
- Protected mutations require idempotency where retries can create duplicates or conflicting state.
- The memory firewall redacts or reviews secret-like and injection-like content before public-safe persistence.
- External-link ingestion rejects credential-bearing URLs, unsupported schemes, and private or loopback hosts. Link metadata never authorizes a fetch.
- Distributed sync validates device status, authority epoch, parent revision, tombstone state, and idempotency before changing the authoritative head.
- MemoryEndpoints is a memory and coordination service, not an arbitrary-code execution host.

The expected behavior for unsupported, unauthorized, malformed, quota-blocked, or conflict-gated requests is an explicit redacted safe no-op response. Safe no-op means the operation did not occur; it is never a disguised success.

## Evidence Limits

Secret scans cover known patterns but are not proof that no unknown sensitive fact exists. Schemas, manifests, signatures, robots files, capability declarations, and model consensus do not grant authorization. See [System Architecture](docs/system-architecture.md) for the complete trust and evidence model.
