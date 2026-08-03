# Deployment

Deployment is intentionally conservative and secret-safe. Credentials stay outside Git in ignored local handoffs or the operator's FileZilla profile and must never be printed, committed, copied into reports, or included in final answers.

## Package

Build the production package:

```powershell
python scripts\package_memoryendpoints.py --json-out var\reports\package-verification-report.json
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

The FileZilla MemoryEndpoints.com profile logs into the MemoryEndpoints.com deployment root, so the deploy script can use the login root without printing credential values:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --dry-run --filezilla-site-match memoryendpoints --protocol ftps --json-out var\reports\deploy-dry-run-latest.json
```

The dry run must resolve host, user, password, package, and remote directory without printing credential values.

## Connection Check

Before a live upload, verify the selected transport and remote directory without uploading files:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --connection-check --filezilla-site-match memoryendpoints --protocol ftps --json-out var\reports\deploy-connection-check-latest.json
```

The default protocol is explicit FTPS. If the hosting handoff explicitly requires plain FTP, rerun the connection check with `--protocol ftp` before attempting upload. Connection-check reports are redacted and always use `uploadedCount: 0`.

## Live Upload

Run only after the local gate and dry run pass:

```powershell
python scripts\ftp_deploy_memoryendpoints.py --filezilla-site-match memoryendpoints --protocol ftps --json-out var\reports\deploy-live-attempt-latest.json
```

Current status: live upload succeeds through the FileZilla-backed explicit FTPS path and requests Passenger restart. The package file count changes with the checked-in source and must be read from the current package and deploy reports rather than copied into documentation. Plain FTP is not the verified publish route.

## Post-Deploy Gate

After a successful upload:

```powershell
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --json-out var\reports\live-route-verification.json
python scripts\verify_memoryendpoints.py --base-url https://memoryendpoints.com --expect-git-head --json-out var\reports\live-latest-code-verification.json
python scripts\build_deploy_attempt_report.py
python scripts\build_readiness_reports.py --write
```

Do not claim the newest code is live until the live upload succeeds, Passenger restart is requested, live route verification passes for the required public routes, and `/api/version` reports the expected source SHA.

Production database verification is a separate hard gate. Configure `MEMORYENDPOINTS_STORE_BACKEND=mysql` plus an ignored `.local-secrets/mysql.json` file on the host, `MEMORYENDPOINTS_MYSQL_*`, or `MEMORYENDPOINTS_MYSQL_URL`, then run:

```powershell
python scripts\verify_mysql_backend.py --base-url https://memoryendpoints.com --json-out var\reports\live-mysql-backend-verification.json
```

The verifier must report `storeBackend` as `mysql` or `mariadb` and `storeBackendVerified` as `true` before live dogfood or the human-verifier account should be created.

If the database values are stored in a local ignored `.local-secrets/mysql.json` file, upload only that secret file to the application root with:

```powershell
python scripts\upload_mysql_secret_config.py --dry-run --filezilla-site-match memoryendpoints --protocol ftps
python scripts\upload_mysql_secret_config.py --connection-check --filezilla-site-match memoryendpoints --protocol ftps
python scripts\upload_mysql_secret_config.py --filezilla-site-match memoryendpoints --protocol ftps
```

When `.local-secrets/mysql.json` exists, the runtime treats it as the authoritative MySQL credential source over URL and individual environment variables.

The upload report is redacted and must not print the host, user, password, database name, or raw remote path.

Do not claim live dogfooding until the live authenticated MATM workflow is verified and a redacted report proves it.

## MultiAgentMemory.com Companion Site

MultiAgentMemory.com is a static documentation companion site, not the Python WSGI endpoint. Its source lives in `sites/multiagentmemory.com/`.

The companion release uses one immutable ZIP and one adjacent external release-identity JSON file through two explicit phases. The deterministic ZIP contains exactly the 16 allowlisted public files and no embedded manifest. The external JSON contains the nested site and package manifests, describes and hashes the ZIP, and binds a clean local commit, the canonical **required** annotated tag name/ref/URL/target, the preactivation remote-`main` lease, release-ledger hash, site aggregate, ZIP hash, website version, UTC activation date, and closed cutover order. Preactivation proves the required tag is absent locally and remotely. Final qualification parses the annotated tag object's own headers and proves the local and remote tag objects are identical and target the bound commit. Observed tag state is phase evidence; it is not embedded as a false preactivation claim in the immutable identity.

The public `releases.json` ledger contains only deployed or withdrawn records. Source review, package inspection, and failed attempts remain private operational evidence. Never create a public predeployment ledger row, move a tag, recreate a tag, force-push a release tag, or publish `main` before live activation.

### 1. Render, test, and commit locally only

Update the intended version, activation date, changes, milestones, and canonical required source-tag evidence in `sites/multiagentmemory.com/releases.json`, then render and verify every derived surface:

```powershell
py -3 scripts\render_multiagentmemory_release_history.py --write
py -3 scripts\render_multiagentmemory_release_history.py --check
py -3 -m unittest tests.test_public_release_history tests.test_multiagentmemory_release_identity tests.test_deploy_protocols tests.test_static_site
py -3 -m unittest discover -s tests
py -3 scripts\verify_static_site.py --json-out var\reports\multiagentmemory-static-site-verification.json
py -3 scripts\secret_scan.py --json-out var\reports\secret-scan-report.json
py -3 scripts\audit_repository_boundary.py --json-out var\reports\repository-boundary-audit.json
git diff --check
```

Commit the complete accepted source change locally. Do not create a tag and do not push the commit. Set the exact identity variables and prove the worktree is clean:

```powershell
$VERSION = "1.0.0"
$TAG = "multiagentmemory-site-v$VERSION"
$TAG_REF = "refs/tags/$TAG"
$SOURCE_COMMIT = git rev-parse HEAD
if (git status --porcelain=v1 --untracked-files=all) { throw "Release source is dirty." }
```

### 2. Build one immutable package in preactivation

All three commands require `--phase preactivation`. They fail unless the local and remote canonical tag refs are both completely absent. The package identity uses `requiredTagName`, `requiredTagRef`, `requiredTagUrl`, and `requiredTagTargetCommitSha`; it does not pretend the tag exists.

```powershell
py -3 scripts\package_multiagentmemory_static_site.py --inspect --phase preactivation --repo-root . --site-root sites\multiagentmemory.com --json-out var\reports\multiagentmemory-package-inspection.json
$SITE_AGGREGATE_SHA256 = (Get-Content var\reports\multiagentmemory-package-inspection.json -Raw | ConvertFrom-Json).siteManifest.aggregateSha256
py -3 scripts\package_multiagentmemory_static_site.py --write --phase preactivation --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --expected-site-aggregate-sha256 $SITE_AGGREGATE_SHA256 --json-out var\reports\multiagentmemory-package-write.json
py -3 scripts\package_multiagentmemory_static_site.py --verify --phase preactivation --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --json-out var\reports\multiagentmemory-package-preactivation-verification.json
```

Keep the ZIP and identity manifest outside tracked source. Do not alter or regenerate either artifact after inspection. A tag appearing locally or remotely consumes this preactivation attempt and every package/deploy/live preactivation command must stop before network mutation.

### 3. Prove only the FTPS target

This target-only check resolves the target profile and remote directory. It performs no source/package qualification and no upload; package and phase arguments are rejected:

```powershell
py -3 scripts\ftp_deploy_static_site.py --connection-check --filezilla-site-match multiagentmemory --target-domain multiagentmemory.com --protocol ftps --json-out var\reports\multiagentmemory-deploy-connection-check-latest.json
```

### 4. Stage only non-claim bytes

Run only while the ledger activation date is the current UTC date. The preactivation deploy re-proves the clean source, exact commit/site/package identity, bound remote-`main` lease, complete local and remote tag absence, target binding, and activation date before mutation. It then performs STOR followed by exact RETR for only these ten non-claim paths:

1. `.well-known/ai-agent.json`
2. `.well-known/mcp.json`
3. `docs/api-reference.html`
4. `docs/how-it-works.html`
5. `docs/memory-boundary.html`
6. `index.html`
7. `robots.txt`
8. `sitemap.xml`
9. `static/favicon.svg`
10. `static/site.css`

It must not STOR any of the six release-claim paths during preactivation.

```powershell
py -3 scripts\ftp_deploy_static_site.py --phase preactivation --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --package-manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --filezilla-site-match multiagentmemory --target-domain multiagentmemory.com --protocol ftps --json-out var\reports\multiagentmemory-nonclaim-stage.json
```

Continue only when the report status is `nonclaims_staged_preactivation`, `claimsExposed` is `false`, `uploadedCount` and `readbackVerifiedCount` are both `10`, and the release-identity digest matches the immutable external manifest. Any attempted STOR is possible remote mutation; record a partial failure truthfully and do not substitute new bytes.

### 5. Prove the ten staged routes over canonical HTTPS

The preactivation verifier accepts exactly `https://multiagentmemory.com` as its base origin. It rejects HTTP, alternate hosts, user info, ports, paths, queries, fragments, redirects, final-origin drift, non-200 responses, wrong media types, and byte drift. It re-proves tag absence and the bound package/source identity before and after downloading exactly the ten non-claim routes. It does not request a release-claim route.

```powershell
py -3 scripts\verify_static_site.py --base-url https://multiagentmemory.com --phase preactivation --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --package-manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --json-out var\reports\multiagentmemory-live-preactivation-verification.json
```

Continue only when the status is `nonclaims_live_verified_preactivation`, `fileCount` and `nonClaimFileCount` are both `10`, `claimFileCount` is `0`, `claimsVerified` is `false`, and the UTC activation gate remains true. This proves that the verifier did not request a claim route; it does not infer the state of unrequested remote routes.

### 6. Requalify immediately before creating the tag

After the ten-route HTTPS proof and immediately before the first tag command, run the release dry run against the unchanged artifacts. This is the last pre-tag source/package/remote-`main` lease/UTC requalification. It performs no upload. Any failure or any intervening source, package, remote-main, tag, or UTC change stops this release attempt.

```powershell
py -3 scripts\ftp_deploy_static_site.py --dry-run --phase preactivation --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --package-manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --filezilla-site-match multiagentmemory --target-domain multiagentmemory.com --protocol ftps --json-out var\reports\multiagentmemory-pretag-requalification.json
```

### 7. Publish the exact annotated tag, then prove final identity

Create the canonical annotated tag on the already-bound commit and push **the tag before `main`**. Lightweight tags are forbidden. Never use `--force`, and never move, delete, or recreate a release tag.

```powershell
git tag --annotate $TAG --message "MultiAgentMemory.com $VERSION" $SOURCE_COMMIT
if ((git cat-file -t $TAG_REF) -ne "tag") { throw "Release tag is not annotated." }
if ((git rev-parse "$TAG_REF^{commit}") -ne $SOURCE_COMMIT) { throw "Release tag target changed." }
git push origin "${TAG_REF}:${TAG_REF}"
py -3 scripts\package_multiagentmemory_static_site.py --verify --phase final --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --json-out var\reports\multiagentmemory-package-final-verification.json
```

Final qualification requires an annotated local tag object whose internal `object`, `type`, and `tag` headers bind the exact commit, declare `type commit`, and name `$TAG`. It also requires both remote raw tag-object and peeled `^{}` records, byte-identical local and remote tag objects, and exact commit/site/package identity. The ZIP and external manifest remain byte-identical across both phases.

### 8. Activate only the six claim paths

The final deploy first RETRs all ten already-staged non-claim paths and requires exact package bytes. It then rechecks the bound source/package/tag identity and UTC activation date immediately before the first claim STOR. Only then does it STOR and RETR the six claims in this canonical order:

1. `ai-manifest.json`
2. `ai.txt`
3. `llms.txt`
4. `README.md`
5. `releases/index.html`
6. `releases.json`

The final phase never re-STORs a non-claim path. Its last two writes are always the human release page followed by the machine ledger.

```powershell
py -3 scripts\ftp_deploy_static_site.py --phase final --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --package-manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --filezilla-site-match multiagentmemory --target-domain multiagentmemory.com --protocol ftps --json-out var\reports\multiagentmemory-claim-activation.json
```

Continue only when the status is `claims_activated_final`, the staged non-claim readback count is `10`, the claim upload and claim readback counts are both `6`, and `claimsExposed` is `true`.

### 9. Prove all 16 canonical HTTPS routes

The final verifier repeats the strict canonical-origin, no-redirect, 200-status, closed-media-type, exact-byte, tag, package, source, and UTC checks across all 16 allowlisted routes:

```powershell
py -3 scripts\verify_static_site.py --base-url https://multiagentmemory.com --phase final --repo-root . --site-root sites\multiagentmemory.com --package "dist\multiagentmemory-site-v$VERSION.zip" --package-manifest "dist\multiagentmemory-site-v$VERSION.manifest.json" --json-out var\reports\multiagentmemory-live-final-verification.json
```

Continue only when the status is `full_live_verified_final`, `fileCount` is `16`, `claimFileCount` is `6`, `claimsVerified` is `true`, the local and remote annotated-tag identity is verified, and the same immutable release-identity digest is reported.

### 10. Advance `main` last

Only after final package qualification, final claim activation, and the full 16-route HTTPS verification return GO may the exact commit be fast-forwarded to `main`:

```powershell
git push origin "${SOURCE_COMMIT}:refs/heads/main"
```

If this push is rejected because remote `main` advanced concurrently, do not move, delete, recreate, or force-push the release tag. The immutable tag remains the release evidence and final verification remains bound to it. Reconcile `main` separately with normal non-destructive history. A main race must never rewrite the released commit or tag.

### Recovery truth

- Before any STOR: correct the reported local input or target problem and rerun only if the exact package, absent-tag state, remote-main lease, and UTC date remain valid.
- After a preactivation STOR: the report is not a safe no-op, but all six claim paths remain untouched. Re-run only the unchanged immutable package after diagnosing the stage/readback failure.
- After ten-route HTTPS GO but before tag push: only the exact canonical annotated tag may be created. A tag collision consumes the version; never move an existing ref.
- After tag push but before claim STOR: the tag is immutable. A final qualification or staged-byte readback failure is a release incident; do not delete or rewrite evidence and do not expose claims.
- During claim activation: public claim state may be mixed. Record the exact partial claim position. Complete and reverify only the unchanged package within the same UTC window, or restore a separately qualified prior production identity.
- After final HTTPS GO: publish only the bound commit to `main`. A rejected `main` push is coordination drift, not permission to change the release tag.
