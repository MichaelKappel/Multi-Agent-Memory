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

The package builder writes ignored public-safe build provenance to `memoryendpoints/build_info.generated.json` and includes it in the deploy package. `/api/version` exposes the deployed source SHA so latest-code deployment can be proven after upload.

## Dry Run

The FTP login directory is the MemoryEndpoints.com deployment root, so use `--remote-dir .`:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --dry-run --handoff E:\ftp_Deploy.txt --remote-dir . --json-out docs\reports\deploy-dry-run-latest.json
```

The dry run must resolve host, user, password, package, and remote directory without printing credential values.

## Connection Check

Before a live upload, verify the selected transport and remote directory without uploading files:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --connection-check --handoff E:\ftp_Deploy.txt --remote-dir . --protocol ftps --json-out docs\reports\deploy-connection-check-latest.json
```

The default protocol is explicit FTPS. If the hosting handoff explicitly requires plain FTP, rerun the connection check with `--protocol ftp` before attempting upload. Connection-check reports are redacted and always use `uploadedCount: 0`.

## Live Upload

Run only after the local gate and dry run pass:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --handoff E:\ftp_Deploy.txt --remote-dir . --protocol ftps --json-out docs\reports\deploy-live-attempt-latest.json
```

Current status: live upload is blocked. The latest recorded no-upload connection checks failed during login for both explicit FTPS and plain FTP with zero files uploaded. See `docs/reports/deploy-connection-check-latest.json`, `docs/reports/deploy-connection-check-ftp-latest.json`, and `docs/reports/deploy-attempt-20260709.json`.

## Post-Deploy Gate

After a successful upload:

```powershell
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --json-out docs\reports\live-route-verification.json
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --expect-git-head --json-out docs\reports\live-latest-code-verification.json
python scripts\build_deploy_attempt_report.py
python scripts\build_readiness_reports.py --write
```

Do not claim the newest code is live until the live upload succeeds, Passenger restart is requested, live route verification passes for the required public routes, and `/api/version` reports the expected source SHA.

Do not claim live dogfooding until the live authenticated MATM workflow is verified and a redacted report proves it.

## MultiAgentMemory.com Companion Site

MultiAgentMemory.com is a static documentation companion site, not the Python WSGI endpoint. Its source lives in `sites/multiagentmemory.com/`.

Dry-run the target-specific static deploy:

```powershell
python scripts\ftp_deploy_static_site.py --dry-run --filezilla-site-match multiagentmemory --target-domain multiagentmemory.com --protocol ftps --json-out docs\reports\multiagentmemory-deploy-dry-run-latest.json
```

Verify login and the target directory without uploading:

```powershell
python scripts\ftp_deploy_static_site.py --connection-check --filezilla-site-match multiagentmemory --target-domain multiagentmemory.com --protocol ftps --json-out docs\reports\multiagentmemory-deploy-connection-check-latest.json
```

The stale `E:\ftp_Deploy.txt` MultiAgentMemory section is not the working credential source. The current working publish path uses the local FileZilla site profile matched by `multiagentmemory`; reports record only redacted FileZilla profile metadata and never print host, user, or password values.

Publish to the target login root only after the FileZilla-backed dry run and connection check pass:

```powershell
python scripts\ftp_deploy_static_site.py --filezilla-site-match multiagentmemory --target-domain multiagentmemory.com --protocol ftps --json-out docs\reports\multiagentmemory-deploy-live-attempt-latest.json
```

Current status: live upload succeeded through the FileZilla-backed explicit FTPS path. The latest recorded publish uploaded 12 static files and wrote a deployment marker. The live site verifier reports zero failures for the expected companion pages and discovery files.

After a successful static upload, verify the public domain:

```powershell
python scripts\verify_static_site.py --base-url https://multiagentmemory.com --json-out docs\reports\multiagentmemory-live-site-verification.json
```
