# Enterprise test gate

From the repository root:

```powershell
python -m pip install -r requirements-test.txt
python scripts/run_enterprise_tests.py --mode hermetic --artifacts "$env:TEMP\matm-enterprise-tests"
```

The hermetic suite uses deterministic settings, synthetic credentials,
isolated writable temporary paths, SQLite-only state, and loopback-only
networking. It does not contact or mutate a deployment. Live, MySQL, or
dogfood-named tests are an explicit external suite:

```powershell
python scripts/run_enterprise_tests.py --mode full --artifacts "$env:TEMP\matm-enterprise-tests-full"
```

The runner emits JUnit, coverage JSON, failure and skip inventories,
environment diagnostics, and sanitized output. It fails closed for missing
dependencies, test failures, critical skips, network attempts, or coverage
below 90% statements / 85% branches. Identity/security and recovery/lifecycle
capabilities must be complete before the enterprise gate can pass. Live,
browser, MySQL/MariaDB, deployment, and external participation remain
separate evidence classes.

The shared runtime contract suite is intentionally copied byte-for-byte to
`tests/test_shared_runtime_contracts.py` in this repository and
MemoryEndpoints.com. Changes to mirrored security, export, history, link,
HTTP, or human-access behavior should update and run both copies together.

The contracts in `tests/test_mysql_store.py` and
`tests/test_commons_mysql.py` are admitted to the hermetic gate because their
MySQL names are historical: the admitted cases use fake connections and
temporary File/SQLite stores only. Real-MySQL cases remain explicit external
skips.
