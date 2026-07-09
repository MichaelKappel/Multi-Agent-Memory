# Deployment

Date: 2026-07-09

Deployment is intentionally conservative and secret-safe. Credentials stay outside Git in `E:\ftp_Deploy.txt` and must never be printed, committed, copied into reports, or included in final answers.

## Package

Build the production package:

```powershell
python scripts\package_memoryendpoints.py --json-out docs\reports\package-verification-report.json
```

The package builder excludes local runtime state and credential surfaces, including:

- `.git`
- `.github`
- `.uai`
- `.local-secrets`
- `var`
- `dist`
- `agent-file-handoff/Content`
- `agent-file-handoff/Improvement`
- `agent-file-handoff/Archive`
- `docs/prompts`
- logs, caches, local databases, SQLite journals, temporary files, and `ftp_Deploy.txt`

## Dry Run

The FTP login directory is the MemoryEndpoints.com deployment root, so use `--remote-dir .`:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --dry-run --handoff E:\ftp_Deploy.txt --remote-dir . --json-out docs\reports\deploy-dry-run-latest.json
```

The dry run must resolve host, user, password, package, and remote directory without printing credential values.

## Live Upload

Run only after the local gate and dry run pass:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --handoff E:\ftp_Deploy.txt --remote-dir . --json-out docs\reports\deploy-live-attempt-latest.json
```

Current status: live upload is blocked. The latest recorded attempt failed during FTPS login with zero files uploaded. See `docs/reports/deploy-attempt-20260709.json`.

## Post-Deploy Gate

After a successful upload:

```powershell
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --json-out docs\reports\live-route-verification.json
python scripts\build_deploy_attempt_report.py
python scripts\build_readiness_reports.py --write
```

Do not claim the newest code is live until the live upload succeeds, Passenger restart is requested, and live route verification passes for the required public routes.

Do not claim live dogfooding until the live authenticated MATM workflow is verified and a redacted report proves it.

## MultiAgentMemory.com Companion Site

MultiAgentMemory.com is a static documentation companion site, not the Python WSGI endpoint. Its source lives in `sites/multiagentmemory.com/`.

Dry-run the target-specific static deploy:

```powershell
python scripts\ftp_deploy_static_site.py --dry-run --discover-remote-dir --target-domain multiagentmemory.com --json-out docs\reports\multiagentmemory-deploy-dry-run-latest.json
```

Publish to the target login root only after the dry run resolves the intended target:

```powershell
python scripts\ftp_deploy_static_site.py --target-domain multiagentmemory.com --remote-dir . --json-out docs\reports\multiagentmemory-deploy-live-attempt-latest.json
```

Current status: live upload is blocked. The latest recorded attempt selected the MultiAgentMemory target section and resolved host, user, password, and port, but FTPS login was rejected before upload. Uploaded file count was zero.

After a successful static upload, verify the public domain:

```powershell
python scripts\verify_static_site.py --base-url https://multiagentmemory.com --json-out docs\reports\multiagentmemory-live-site-verification.json
```
