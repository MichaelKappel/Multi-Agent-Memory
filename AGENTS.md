# AGENTS.md

This repository is MemoryEndpoints.com, a pure Python/TypeScript/HTML5 MATM endpoint reference.

## Startup Order

1. Read `.uai/memory-maintenance.uai`.
2. Read `.uai/identity.uai`, `.uai/world-context.uai`, `.uai/totem.uai`, `.uai/taboo.uai`, and `.uai/talisman.uai`.
3. Read `.uai/startup-packet.uai`, then follow its complete ordered manifest without inventing a catch-all active-memory file.
4. Inspect active file handoff buckets one item at a time:
   - `agent-file-handoff/Content`
   - `agent-file-handoff/Improvement`
5. Use the full `.uai/` suite as active startup memory.
6. Use MemoryEndpoints.com as the live mid-to-long-term MATM memory boundary when reachable and authenticated.
7. Use MultiAgentMemory.com as the GitHub companion documentation site.
8. Coordinate active work through protected MemoryEndpoints meeting rooms. Record concise cold-start continuity in typed `.uai` files and point-in-time verifier output under ignored `var/reports/`.

## Hard Rules

- Do not print or commit secrets.
- Do not commit deployment handoffs, FileZilla credentials, local secret files, or report prompts.
- Keep runtime code dependency-free unless the maintainer explicitly approves a dependency.
- Do not copy NeuralWikis public wiki pages, branding, or claims.
- Keep public claims bounded by evidence.
- Protected MATM mutation routes must use public-safe summaries and idempotency keys when retrying writes.
- Agent current-message work enters through `/api/matm/current-message`; acknowledge handled notifications through `/api/matm/notifications/ack`.
- New agents enter through the company meeting room and receive a structured routing decision before project, goal, or task work. Durable wiki ownership remains company, workspace, or project only.
- Check `/api/matm/workspace` before large writes. Free agent workspaces have a 200 MB quota.
- Local `.uai` stays active always. Hosted MATM augments durable memory; it never replaces local startup continuity.

## Verification

Run:

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi
python scripts\package_memoryendpoints.py --check-only
python scripts\secret_scan.py
python scripts\audit_uai_memory.py
python scripts\verify_static_site.py
python scripts\enterprise_readiness_audit.py --run-checks
```

## Deployment

Use `scripts/ftp_deploy_memoryendpoints.py` only after tests pass. The script must resolve host, user, password, package, and remote directory while redacting values. Run explicit-FTPS dry-run and connection-check gates before the live upload.

The verified FileZilla profile logs into the MemoryEndpoints.com deployment root. Let the deployer use that login root unless the hosting configuration explicitly changes.
