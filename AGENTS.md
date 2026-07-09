# AGENTS.md

This repository is MemoryEndpoints.com, a pure Python/TypeScript/HTML5 MATM endpoint reference.

## Startup Order

1. Read `.uai/constraints.uai`.
2. Read `.uai/startup-packet.uai`.
3. Inspect active file handoff buckets:
   - `agent-file-handoff/Content`
   - `agent-file-handoff/Improvement`
4. Use `.uai/` as short-term/startup memory.
5. Use MemoryEndpoints.com as the live mid-to-long-term MATM memory boundary.
6. Use MultiAgentMemory.com as the GitHub companion documentation site.
7. Record progress in `.uai/progress.uai` and reports under `docs/reports/`.

## Hard Rules

- Do not print or commit secrets.
- Do not commit `E:\ftp_Deploy.txt`.
- Keep runtime code dependency-free unless the maintainer explicitly approves a dependency.
- Do not copy NeuralWikis public wiki pages, branding, or claims.
- Keep public claims bounded by evidence.
- Protected MATM mutation routes must use public-safe summaries and idempotency keys when retrying writes.
- Agent current-message work enters through `/api/matm/current-message`; acknowledge handled notifications through `/api/matm/notifications/ack`.
- Check `/api/matm/workspace` before large writes. Free agent workspaces have a 200 MB quota.

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
