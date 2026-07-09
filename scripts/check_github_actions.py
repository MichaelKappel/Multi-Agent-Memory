import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPOSITORY = "MichaelKappel/Multi-Agent-Memory"
DEFAULT_BRANCH = "main"
DEFAULT_WORKFLOW_NAME = "CI"
USER_AGENT = "MemoryEndpoints-GitHub-Actions-Checker"


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def api_json(url):
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_runs(repository, branch, max_runs):
    url = "https://api.github.com/repos/%s/actions/runs?branch=%s&per_page=%s" % (
        repository,
        branch,
        max_runs,
    )
    return api_json(url)


def fetch_jobs(jobs_url):
    return api_json(jobs_url)


def _run_matches(run, workflow_name):
    if not workflow_name:
        return True
    return run.get("name") == workflow_name or run.get("workflow_name") == workflow_name


def _safe_run(run, jobs):
    job_items = jobs.get("jobs") if isinstance(jobs, dict) else []
    step_count = sum(len(job.get("steps") or []) for job in job_items)
    return {
        "conclusion": run.get("conclusion"),
        "createdAt": run.get("created_at"),
        "displayTitle": run.get("display_title"),
        "headBranch": run.get("head_branch"),
        "headSha": run.get("head_sha"),
        "htmlUrl": run.get("html_url"),
        "jobCount": len(job_items),
        "jobStepCount": step_count,
        "runId": run.get("id"),
        "runNumber": run.get("run_number"),
        "status": run.get("status"),
        "updatedAt": run.get("updated_at"),
    }


def _blocker(latest):
    if not latest:
        return "No GitHub Actions runs were returned by the public API."
    if latest.get("status") != "completed":
        return "Latest GitHub Actions run is not complete yet."
    if latest.get("conclusion") == "success":
        return None
    if latest.get("jobCount", 0) > 0 and latest.get("jobStepCount", 0) == 0:
        return "Latest GitHub Actions run failed before any workflow steps executed; public job metadata shows zero recorded steps."
    return "Latest GitHub Actions run completed without a success conclusion."


def build_report(repository, branch, workflow_name, runs_payload, jobs_by_run_id, generated_at=None):
    runs = [
        run
        for run in runs_payload.get("workflow_runs", [])
        if run.get("head_branch") == branch and _run_matches(run, workflow_name)
    ]
    observed = [_safe_run(run, jobs_by_run_id.get(run.get("id"), {})) for run in runs]
    latest = observed[0] if observed else None
    conclusion = latest.get("conclusion") if latest else None
    status = latest.get("status") if latest else None
    blocker = _blocker(latest)
    return {
        "schemaVersion": "memoryendpoints.github_ci_status.v2",
        "ok": conclusion == "success",
        "repository": repository,
        "branch": branch,
        "workflowName": workflow_name,
        "generatedAt": generated_at or utc_now(),
        "source": "GitHub Actions public runs and jobs API",
        "status": status,
        "conclusion": conclusion,
        "blocker": blocker,
        "latestObservedHeadSha": latest.get("headSha") if latest else None,
        "latestObservedHtmlUrl": latest.get("htmlUrl") if latest else None,
        "latestObservedJobCount": latest.get("jobCount") if latest else 0,
        "latestObservedJobStepCount": latest.get("jobStepCount") if latest else 0,
        "observedRunCount": len(observed),
        "observedRuns": observed,
        "valuesRedacted": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--workflow-name", default=DEFAULT_WORKFLOW_NAME)
    parser.add_argument("--max-runs", type=int, default=5)
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    try:
        runs_payload = fetch_runs(args.repository, args.branch, args.max_runs)
        matching_runs = [
            run
            for run in runs_payload.get("workflow_runs", [])
            if run.get("head_branch") == args.branch and _run_matches(run, args.workflow_name)
        ]
        jobs_by_run_id = {}
        for run in matching_runs:
            jobs_by_run_id[run.get("id")] = fetch_jobs(run.get("jobs_url"))
        report = build_report(args.repository, args.branch, args.workflow_name, runs_payload, jobs_by_run_id)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        report = {
            "schemaVersion": "memoryendpoints.github_ci_status.v2",
            "ok": False,
            "repository": args.repository,
            "branch": args.branch,
            "workflowName": args.workflow_name,
            "generatedAt": utc_now(),
            "source": "GitHub Actions public runs and jobs API",
            "status": "unavailable",
            "conclusion": "failure",
            "blocker": "Could not read GitHub Actions public API: %s." % exc.__class__.__name__,
            "latestObservedHeadSha": None,
            "latestObservedHtmlUrl": None,
            "latestObservedJobCount": 0,
            "latestObservedJobStepCount": 0,
            "observedRunCount": 0,
            "observedRuns": [],
            "valuesRedacted": True,
        }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
