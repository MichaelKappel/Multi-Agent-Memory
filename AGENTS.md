# AGENTS.md

This repository is MemoryEndpoints.com, a pure Python/TypeScript/HTML5 MATM endpoint reference.

## Startup Order

1. Read `.uai/totem.uai`.
2. Read `.uai/startup-packet.uai`.
3. Read `.uai/constraints.uai`.
4. Inspect active file handoff buckets:
   - `agent-file-handoff/Content`
   - `agent-file-handoff/Improvement`
5. Use `.uai/` as short-term/startup memory.
6. Use MemoryEndpoints.com as the live mid-to-long-term MATM memory boundary when reachable and authenticated.
7. Use MultiAgentMemory.com as the GitHub companion documentation site.
8. Record progress in `.uai/progress.uai` and reports under `docs/reports/`.

## Hard Rules

- Do not print or commit secrets.
- Do not commit `E:\ftp_Deploy.txt`.
- Keep runtime code dependency-free unless the maintainer explicitly approves a dependency.
- Do not copy NeuralWikis public wiki pages, branding, or claims.
- Keep public claims bounded by evidence.
- Protected MATM mutation routes must use public-safe summaries and idempotency keys when retrying writes.
- Agent current-message work enters through `/api/matm/current-message`; acknowledge handled notifications through `/api/matm/notifications/ack`.
- Check `/api/matm/workspace` before large writes. Free agent workspaces have a 200 MB quota.
- Local `.uai` stays active always. Hosted MATM augments durable memory; it never replaces local startup continuity.

## Verification

Run:

```powershell
python -m unittest discover -s tests
python scripts\verify_memoryendpoints.py --wsgi
python scripts\package_memoryendpoints.py --check-only
python scripts\secret_scan.py
```

## Deployment

Use `scripts/ftp_deploy_memoryendpoints.py` only after tests pass. The script must resolve host, user, password, package, and remote directory while redacting values.

The FTP login directory is the MemoryEndpoints.com deployment root. Use `--remote-dir .` for dry-run and live deployment.
