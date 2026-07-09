import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPOSITORY = "MichaelKappel/Multi-Agent-Memory"
DEFAULT_BRANCH = "main"
DEFAULT_WORKFLOW_NAME = "CI"
USER_AGENT = "MemoryEndpoints-GitHub-Actions-Checker"
MAX_SAFE_TEXT = 240


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


def fetch_check_run(check_run_url):
    return api_json(check_run_url)


def fetch_annotations(annotations_url):
    if not annotations_url:
        return []
    payload = api_json(annotations_url)
    return payload if isinstance(payload, list) else []


def safe_text(value):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"(?i)\b(password|passwd|pwd|secret|token|api[_ -]?key)\b\s*[:=]\s*\S+", r"\1=[redacted]", text)
    if len(text) > MAX_SAFE_TEXT:
        return text[: MAX_SAFE_TEXT - 3] + "..."
    return text


def safe_annotation(annotation):
    return {
        "annotationLevel": safe_text(annotation.get("annotation_level")),
        "path": safe_text(annotation.get("path")),
        "startLine": annotation.get("start_line"),
        "endLine": annotation.get("end_line"),
        "message": safe_text(annotation.get("message")),
        "title": safe_text(annotation.get("title")),
        "valuesRedacted": True,
    }


def safe_error(exc):
    if isinstance(exc, HTTPError):
        return "HTTPError status %s" % getattr(exc, "code", "unknown")
    return exc.__class__.__name__


def previous_report_summary(path):
    if not path or not Path(path).exists():
        return None
    try:
        previous = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "available": True,
        "generatedAt": safe_text(previous.get("generatedAt")),
        "status": safe_text(previous.get("status")),
        "conclusion": safe_text(previous.get("conclusion")),
        "blocker": safe_text(previous.get("blocker")),
        "latestObservedHeadSha": safe_text(previous.get("latestObservedHeadSha")),
        "latestObservedHtmlUrl": safe_text(previous.get("latestObservedHtmlUrl")),
        "valuesRedacted": True,
    }


def _run_matches(run, workflow_name):
    if not workflow_name:
        return True
    return run.get("name") == workflow_name or run.get("workflow_name") == workflow_name


def _safe_run(run, jobs):
    job_items = jobs.get("jobs") if isinstance(jobs, dict) else []
    step_count = sum(len(job.get("steps") or []) for job in job_items)
    annotations = []
    for job in job_items:
        check_run = job.get("checkRun") or {}
        annotations.extend(check_run.get("annotations") or [])
    return {
        "conclusion": run.get("conclusion"),
        "createdAt": run.get("created_at"),
        "displayTitle": run.get("display_title"),
        "headBranch": run.get("head_branch"),
        "headSha": run.get("head_sha"),
        "htmlUrl": run.get("html_url"),
        "jobCount": len(job_items),
        "jobStepCount": step_count,
        "jobAnnotationCount": len(annotations),
        "jobAnnotations": annotations[:5],
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
    annotations = latest.get("jobAnnotations") or []
    for annotation in annotations:
        message = annotation.get("message")
        if message:
            if latest.get("jobStepCount", 0) == 0:
                return "Latest GitHub Actions run failed before workflow steps executed: %s" % message
            return "Latest GitHub Actions run reported: %s" % message
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
        "latestObservedJobAnnotationCount": latest.get("jobAnnotationCount") if latest else 0,
        "latestObservedJobAnnotations": latest.get("jobAnnotations") if latest else [],
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
            jobs_payload = fetch_jobs(run.get("jobs_url"))
            for job in jobs_payload.get("jobs", []):
                check_run_url = job.get("check_run_url")
                if not check_run_url:
                    continue
                check_run = fetch_check_run(check_run_url)
                output = check_run.get("output") or {}
                annotations = []
                if output.get("annotations_count"):
                    annotations = [safe_annotation(item) for item in fetch_annotations(output.get("annotations_url"))]
                job["checkRun"] = {
                    "annotations": annotations,
                    "annotationsCount": output.get("annotations_count", len(annotations)),
                    "outputTitle": safe_text(output.get("title")),
                    "outputSummary": safe_text(output.get("summary")),
                    "valuesRedacted": True,
                }
            jobs_by_run_id[run.get("id")] = jobs_payload
        report = build_report(args.repository, args.branch, args.workflow_name, runs_payload, jobs_by_run_id)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        previous_summary = previous_report_summary(args.json_out) if args.json_out else None
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
            "blocker": "Could not read GitHub Actions public API: %s." % safe_error(exc),
            "latestObservedHeadSha": None,
            "latestObservedHtmlUrl": None,
            "latestObservedJobCount": 0,
            "latestObservedJobStepCount": 0,
            "latestObservedJobAnnotationCount": 0,
            "latestObservedJobAnnotations": [],
            "observedRunCount": 0,
            "observedRuns": [],
            "valuesRedacted": True,
        }
        if previous_summary:
            report["previousReport"] = previous_summary

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
