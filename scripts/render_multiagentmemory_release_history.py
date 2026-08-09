"""Render and verify MultiAgentMemory.com release projections from releases.json."""

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .multiagentmemory_release_identity import tag_url_for_version
except ImportError:
    from multiagentmemory_release_identity import tag_url_for_version


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITE_ROOT = ROOT / "sites" / "multiagentmemory.com"
CANONICAL_URL = "https://multiagentmemory.com/releases/"
MACHINE_URL = "https://multiagentmemory.com/releases.json"
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
TOP_LEVEL_FIELDS = (
    "schema",
    "schemaVersion",
    "site",
    "canonicalUrl",
    "machineUrl",
    "recordPolicy",
    "versionScopes",
    "publicEditionHistory",
    "currentProductionWebsiteVersion",
    "releaseCount",
    "releases",
)
PUBLIC_EDITION_HISTORY_FIELDS = ("currentVersion", "releaseCount", "releases")
PUBLIC_EDITION_RELEASE_FIELDS = (
    "version",
    "releaseDate",
    "status",
    "title",
    "summary",
    "changes",
    "milestones",
    "evidence",
)
RELEASE_FIELDS = (
    "version",
    "activationDate",
    "activationTimezone",
    "status",
    "title",
    "summary",
    "changes",
    "milestones",
    "evidence",
)


class ReleaseProjectionError(ValueError):
    """Raised when the authoritative ledger cannot produce safe projections."""


def _require(condition, message):
    if not condition:
        raise ReleaseProjectionError(message)


def _plain_text(value, field):
    _require(
        isinstance(value, str) and value.strip() == value and value,
        f"{field} is invalid",
    )
    _require(
        "\x00" not in value and "\r" not in value and "\n" not in value,
        f"{field} must be one line",
    )
    return value


def _semver_key(value):
    match = SEMVER.fullmatch(value or "")
    _require(match is not None, "release version must be exact three-part SemVer")
    return tuple(int(part) for part in match.groups())


def _public_evidence_url(value, version):
    value = _plain_text(value, "evidence.url")
    parsed = urlsplit(value)
    _require(parsed.scheme == "https", "evidence URL must use HTTPS")
    _require(parsed.hostname == "github.com", "source-tag evidence must use github.com")
    _require(
        not parsed.username and not parsed.password,
        "evidence URL must not contain credentials",
    )
    _require(
        not parsed.query and not parsed.fragment,
        "source-tag evidence URL must be canonical",
    )
    _require(
        value == tag_url_for_version(version),
        "source-tag evidence URL does not match the release version",
    )
    return value


def _public_source_commit(item, version):
    _require(
        isinstance(item, dict)
        and tuple(item) == ("type", "label", "url", "commitSha"),
        f"public edition {version} evidence fields changed",
    )
    _require(item["type"] == "source_commit", "unsupported public edition evidence")
    commit_sha = _plain_text(
        item["commitSha"], f"public edition {version} evidence commitSha"
    )
    _require(
        re.fullmatch(r"[0-9a-f]{40}", commit_sha) is not None,
        f"public edition {version} evidence commitSha is invalid",
    )
    expected_url = (
        "https://github.com/MichaelKappel/Multi-Agent-Memory/commit/" + commit_sha
    )
    _require(item["url"] == expected_url, "public edition commit URL is not exact")
    _require(
        item["label"] == "Source commit " + commit_sha,
        "public edition evidence label is not exact",
    )
    return commit_sha


def load_ledger(site_root=DEFAULT_SITE_ROOT):
    path = Path(site_root) / "releases.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseProjectionError("releases.json is unavailable or invalid") from exc
    validate_ledger(payload)
    return payload


def validate_ledger(payload):
    _require(isinstance(payload, dict), "release ledger must be an object")
    _require(
        tuple(payload) == TOP_LEVEL_FIELDS,
        "release ledger top-level field order changed",
    )
    _require(
        payload["schema"] == "multiagentmemory.public-release-history.v1",
        "unsupported release schema",
    )
    _require(payload["schemaVersion"] == "1.0", "unsupported release schema version")
    _require(payload["site"] == "MultiAgentMemory.com", "release ledger site changed")
    _require(payload["canonicalUrl"] == CANONICAL_URL, "release canonical URL changed")
    _require(payload["machineUrl"] == MACHINE_URL, "release machine URL changed")

    expected_policy = {
        "productionActivatedOnly": True,
        "exactWebsiteSemanticVersionRequired": True,
        "revisionBoundActivationDateRequired": True,
        "activationDateMustEqualSuccessfulUploadUtcDate": True,
        "sourceTagRevisionBindingRequired": True,
        "explicitReleaseStatusRequired": True,
        "sourceCandidatesPublished": False,
        "plannedWorkPublished": False,
        "publicEvidenceRequired": True,
    }
    _require(
        payload["recordPolicy"] == expected_policy, "release record policy changed"
    )
    scopes = payload["versionScopes"]
    _require(
        isinstance(scopes, dict)
        and tuple(scopes)
        == (
            "website",
            "publicEdition",
            "endpointApi",
            "releaseHistorySchema",
            "packageSource",
        ),
        "release version scopes changed",
    )
    _require(
        scopes["endpointApi"].get("currentProductionVersion") is None,
        "endpoint API version was borrowed",
    )
    _require(
        scopes["packageSource"].get("currentProductionVersion") is None,
        "package/source version was borrowed",
    )
    _require(
        scopes["releaseHistorySchema"].get("version") == "1.0",
        "release schema scope changed",
    )

    edition_history = payload["publicEditionHistory"]
    _require(
        isinstance(edition_history, dict)
        and tuple(edition_history) == PUBLIC_EDITION_HISTORY_FIELDS,
        "public edition history fields changed",
    )
    edition_releases = edition_history["releases"]
    _require(
        isinstance(edition_releases, list) and edition_releases,
        "public edition history must not be empty",
    )
    _require(
        edition_history["releaseCount"] == len(edition_releases),
        "public edition releaseCount does not match releases",
    )
    edition_versions = []
    edition_dates = []
    edition_current = []
    for index, release in enumerate(edition_releases):
        _require(
            isinstance(release, dict)
            and tuple(release) == PUBLIC_EDITION_RELEASE_FIELDS,
            f"public edition release {index} fields changed",
        )
        version = _plain_text(
            release["version"], f"publicEditionHistory.releases[{index}].version"
        )
        edition_versions.append((_semver_key(version), version))
        try:
            release_date = date.fromisoformat(release["releaseDate"])
        except (TypeError, ValueError) as exc:
            raise ReleaseProjectionError(
                f"public edition {version} releaseDate is invalid"
            ) from exc
        _require(
            release["releaseDate"] == release_date.isoformat(),
            f"public edition {version} releaseDate is not canonical",
        )
        edition_dates.append(release_date)
        _require(
            release["status"] in {"current", "historical"},
            f"public edition {version} status is invalid",
        )
        if release["status"] == "current":
            edition_current.append(version)
        _plain_text(release["title"], f"public edition {version} title")
        _plain_text(release["summary"], f"public edition {version} summary")
        for field in ("changes", "milestones"):
            values = release[field]
            _require(
                isinstance(values, list) and values,
                f"public edition {version} has no {field}",
            )
            for item in values:
                _plain_text(item, f"public edition {version} {field}")
        evidence = release["evidence"]
        _require(
            isinstance(evidence, list) and len(evidence) == 1,
            f"public edition {version} must have one source commit",
        )
        _public_source_commit(evidence[0], version)
    _require(
        edition_versions
        == sorted(edition_versions, key=lambda item: item[0], reverse=True),
        "public edition releases must be newest version first",
    )
    _require(
        edition_dates == sorted(edition_dates, reverse=True),
        "public edition releases must be newest date first",
    )
    _require(
        len({version for _key, version in edition_versions})
        == len(edition_versions),
        "public edition release versions must be unique",
    )
    _require(len(edition_current) == 1, "public edition must have one current release")
    _require(
        edition_history["currentVersion"] == edition_current[0],
        "current public edition version does not match its release",
    )
    _require(
        scopes["publicEdition"].get("currentProductionVersion")
        == edition_current[0],
        "public edition version scope drifted",
    )

    releases = payload["releases"]
    _require(isinstance(releases, list), "releases must be a list")
    _require(
        payload["releaseCount"] == len(releases), "releaseCount does not match releases"
    )
    versions = []
    activation_dates = []
    for index, release in enumerate(releases):
        _require(
            isinstance(release, dict) and tuple(release) == RELEASE_FIELDS,
            f"release {index} fields changed",
        )
        version = _plain_text(release["version"], f"releases[{index}].version")
        versions.append((_semver_key(version), version))
        try:
            activation = date.fromisoformat(release["activationDate"])
        except (TypeError, ValueError) as exc:
            raise ReleaseProjectionError(
                f"release {version} activationDate is invalid"
            ) from exc
        _require(
            release["activationDate"] == activation.isoformat(),
            f"release {version} activationDate is not canonical",
        )
        _require(
            release["activationTimezone"] == "UTC",
            f"release {version} activation timezone must be UTC",
        )
        _require(
            release["status"] in {"deployed", "withdrawn"},
            f"release {version} status is invalid",
        )
        activation_dates.append(activation)
        _plain_text(release["title"], f"release {version} title")
        _plain_text(release["summary"], f"release {version} summary")

        changes = release["changes"]
        _require(
            isinstance(changes, list) and changes, f"release {version} has no changes"
        )
        change_areas = []
        for change in changes:
            _require(
                isinstance(change, dict) and tuple(change) == ("area", "summary"),
                f"release {version} change fields changed",
            )
            change_areas.append(
                _plain_text(change["area"], f"release {version} change area")
            )
            _plain_text(change["summary"], f"release {version} change summary")
        _require(
            len(change_areas) == len(set(change_areas)),
            f"release {version} repeats a change area",
        )

        milestones = release["milestones"]
        _require(
            isinstance(milestones, list) and milestones,
            f"release {version} has no milestone",
        )
        for milestone in milestones:
            _require(
                isinstance(milestone, dict) and tuple(milestone) == ("name", "summary"),
                f"release {version} milestone fields changed",
            )
            _plain_text(milestone["name"], f"release {version} milestone name")
            _plain_text(milestone["summary"], f"release {version} milestone summary")

        evidence = release["evidence"]
        _require(
            isinstance(evidence, list) and evidence,
            f"release {version} has no public evidence",
        )
        source_tags = []
        for item in evidence:
            _require(
                isinstance(item, dict) and tuple(item) == ("type", "label", "url"),
                f"release {version} evidence fields changed",
            )
            _plain_text(item["label"], f"release {version} evidence label")
            if item["type"] == "source_tag":
                source_tags.append(_public_evidence_url(item["url"], version))
            else:
                raise ReleaseProjectionError(
                    f"release {version} has unsupported evidence type"
                )
        _require(
            len(source_tags) == 1,
            f"release {version} must have exactly one source-tag evidence URL",
        )

    _require(
        len({version for _key, version in versions}) == len(versions),
        "release versions must be unique",
    )
    _require(
        versions == sorted(versions, key=lambda item: item[0], reverse=True),
        "releases must be newest version first",
    )
    _require(
        activation_dates == sorted(activation_dates, reverse=True),
        "releases must be newest activation first",
    )
    deployed_releases = [
        release for release in releases if release["status"] == "deployed"
    ]
    current = deployed_releases[0]["version"] if deployed_releases else None
    _require(
        payload["currentProductionWebsiteVersion"] == current,
        "current website version does not match latest release",
    )
    _require(
        scopes["website"].get("currentProductionVersion") == current,
        "website version scope drifted",
    )


def _json_ld(payload):
    items = []
    for position, release in enumerate(payload["releases"], 1):
        version = release["version"]
        items.append(
            {
                "@type": "ListItem",
                "position": position,
                "item": {
                    "@type": "CreativeWork",
                    "@id": f"{CANONICAL_URL}#v{version}",
                    "url": f"{CANONICAL_URL}#v{version}",
                    "name": f"MultiAgentMemory.com {version}: {release['title']}",
                    "version": version,
                    "datePublished": release["activationDate"],
                    "description": release["summary"],
                    "additionalProperty": {
                        "@type": "PropertyValue",
                        "name": "Production status",
                        "value": release["status"],
                    },
                    "sameAs": [item["url"] for item in release["evidence"]],
                },
            }
        )
    public_editions = []
    for release in payload["publicEditionHistory"]["releases"]:
        public_editions.append(
            {
                "@type": "SoftwareSourceCode",
                "@id": f"{CANONICAL_URL}#public-edition-v{release['version']}",
                "url": f"{CANONICAL_URL}#public-edition-v{release['version']}",
                "name": f"Multi-Agent Memory public edition {release['version']}",
                "version": release["version"],
                "datePublished": release["releaseDate"],
                "description": release["summary"],
                "codeRepository": release["evidence"][0]["url"],
            }
        )
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "@id": f"{CANONICAL_URL}#page",
                "url": CANONICAL_URL,
                "name": "MultiAgentMemory.com production release history",
                "description": "Verified production releases with exact website versions, activation dates, changes, milestones, version scopes, and public evidence.",
                "isPartOf": {
                    "@type": "WebSite",
                    "@id": "https://multiagentmemory.com/#website",
                    "name": "MultiAgentMemory.com",
                    "url": "https://multiagentmemory.com/",
                },
                "breadcrumb": {"@id": f"{CANONICAL_URL}#breadcrumb"},
                "mainEntity": {"@id": f"{CANONICAL_URL}#release-list"},
            },
            {
                "@type": "ItemList",
                "@id": f"{CANONICAL_URL}#release-list",
                "name": "Verified MultiAgentMemory.com production releases",
                "numberOfItems": payload["releaseCount"],
                "itemListElement": items,
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{CANONICAL_URL}#breadcrumb",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "Home",
                        "item": "https://multiagentmemory.com/",
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": "Release history",
                        "item": CANONICAL_URL,
                    },
                ],
            },
            *public_editions,
        ],
    }
    text = json.dumps(graph, indent=2, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _display_date(value):
    parsed = date.fromisoformat(value)
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _release_markup(payload):
    if not payload["releases"]:
        return """      <article class="release-empty-state" aria-labelledby="empty-ledger-title">
        <div class="release-empty-icon" aria-hidden="true">0</div>
        <div>
          <p class="release-empty-kicker">Deployed-only ledger</p>
          <h3 id="empty-ledger-title">No production release currently meets the publication rules.</h3>
          <p>No deployment currently has both an exact website semantic version and revision-bound public evidence.</p>
          <p class="release-empty-note">An empty ledger is evidence discipline, not missing data.</p>
        </div>
      </article>"""
    records = []
    for release in payload["releases"]:
        version = html.escape(release["version"])
        record_id = "release-v" + release["version"].replace(".", "-")
        changes = "\n".join(
            """            <li>
              <h4>{area}</h4>
              <p>{summary}</p>
            </li>""".format(
                area=html.escape(change["area"]), summary=html.escape(change["summary"])
            )
            for change in release["changes"]
        )
        milestones = "\n".join(
            """            <li>
              <strong>{name}</strong>
              <span>{summary}</span>
            </li>""".format(
                name=html.escape(item["name"]), summary=html.escape(item["summary"])
            )
            for item in release["milestones"]
        )
        evidence = "\n".join(
            """            <li><a href="{url}">{label}</a></li>""".format(
                url=html.escape(item["url"], quote=True),
                label=html.escape(item["label"]),
            )
            for item in release["evidence"]
        )
        records.append(
            """      <article class="release-record" id="{record_id}" data-release-record data-version="{version}" data-release-status="{release_status}" aria-labelledby="{record_id}-title">
        <header class="release-record-header">
          <div>
            <p class="release-version">Website version {version} <span class="release-deployment-status">{status_label}</span></p>
            <h3 id="{record_id}-title">{title}</h3>
          </div>
          <p class="release-activation"><span>Production activation</span><time datetime="{activation_date}">{display_date} (UTC)</time></p>
        </header>
        <p class="release-summary">{summary}</p>
        <section aria-labelledby="{record_id}-changes">
          <h4 id="{record_id}-changes" class="release-subheading">What changed</h4>
          <ul class="release-change-grid">
{changes}
          </ul>
        </section>
        <section class="release-milestones" aria-labelledby="{record_id}-milestones">
          <h4 id="{record_id}-milestones" class="release-subheading">Milestones</h4>
          <ul>
{milestones}
          </ul>
        </section>
        <section class="release-evidence" aria-labelledby="{record_id}-evidence">
          <h4 id="{record_id}-evidence" class="release-subheading">Public evidence</h4>
          <ul>
{evidence}
          </ul>
        </section>
      </article>""".format(
                record_id=record_id,
                version=version,
                release_status=html.escape(release["status"], quote=True),
                status_label="Deployed"
                if release["status"] == "deployed"
                else "Withdrawn",
                title=html.escape(release["title"]),
                activation_date=release["activationDate"],
                display_date=_display_date(release["activationDate"]),
                summary=html.escape(release["summary"]),
                changes=changes,
                milestones=milestones,
                evidence=evidence,
            )
        )
    return "\n".join(records)


def _public_edition_markup(payload):
    records = []
    for release in payload["publicEditionHistory"]["releases"]:
        version = html.escape(release["version"])
        record_id = "public-edition-v" + release["version"].replace(".", "-")
        changes = "\n".join(
            f"            <li>{html.escape(item)}</li>" for item in release["changes"]
        )
        milestones = "\n".join(
            f"            <li>{html.escape(item)}</li>"
            for item in release["milestones"]
        )
        evidence = release["evidence"][0]
        status_label = "Current" if release["status"] == "current" else "Historical"
        records.append(
            """      <article class="release-record" id="{record_id}" data-public-edition-record data-version="{version}" data-release-status="{release_status}" aria-labelledby="{record_id}-title">
        <header class="release-record-header">
          <div>
            <p class="release-version">Public edition {version} <span class="release-deployment-status">{status_label}</span></p>
            <h3 id="{record_id}-title">{title}</h3>
          </div>
          <p class="release-activation"><span>Published</span><time datetime="{release_date}">{display_date} (UTC)</time></p>
        </header>
        <p class="release-summary">{summary}</p>
        <section aria-labelledby="{record_id}-changes">
          <h4 id="{record_id}-changes" class="release-subheading">What changed</h4>
          <ul>
{changes}
          </ul>
        </section>
        <section class="release-milestones" aria-labelledby="{record_id}-milestones">
          <h4 id="{record_id}-milestones" class="release-subheading">Milestones</h4>
          <ul>
{milestones}
          </ul>
        </section>
        <section class="release-evidence" aria-labelledby="{record_id}-evidence">
          <h4 id="{record_id}-evidence" class="release-subheading">Exact source provenance</h4>
          <ul><li><a href="{evidence_url}">{evidence_label}</a></li></ul>
        </section>
      </article>""".format(
                record_id=record_id,
                version=version,
                release_status=html.escape(release["status"], quote=True),
                status_label=status_label,
                title=html.escape(release["title"]),
                release_date=release["releaseDate"],
                display_date=_display_date(release["releaseDate"]),
                summary=html.escape(release["summary"]),
                changes=changes,
                milestones=milestones,
                evidence_url=html.escape(evidence["url"], quote=True),
                evidence_label=html.escape(evidence["label"]),
            )
        )
    return "\n".join(records)


def render_release_html(payload):
    current = payload["currentProductionWebsiteVersion"]
    latest = payload["releases"][0] if payload["releases"] else None
    current_display = html.escape(current) if current else "Not established"
    latest_display = (
        f"{_display_date(latest['activationDate'])} (UTC)"
        if latest
        else "No dated record"
    )
    json_ld = _json_ld(payload)
    records = _release_markup(payload)
    public_edition_records = _public_edition_markup(payload)
    public_edition = payload["publicEditionHistory"]
    current_public_edition = html.escape(public_edition["currentVersion"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Production Release History | MultiAgentMemory.com</title>
  <meta name="description" content="Verified MultiAgentMemory.com production releases with exact website versions, activation dates, changes, milestones, version scopes, and public evidence.">
  <meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large">
  <meta name="theme-color" content="#0b5f59">
  <link rel="canonical" href="{CANONICAL_URL}">
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/site.css?v=ui4">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="MultiAgentMemory.com">
  <meta property="og:title" content="Production Release History | MultiAgentMemory.com">
  <meta property="og:description" content="A deployed-only, evidence-bound chronology of MultiAgentMemory.com website releases.">
  <meta property="og:url" content="{CANONICAL_URL}">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="Production Release History | MultiAgentMemory.com">
  <meta name="twitter:description" content="Exact versions, activation dates, changes, milestones, and public evidence for verified production releases.">
  <script type="application/ld+json">
{json_ld}
  </script>
</head>
<body class="release-history-body">
  <a class="skip-link" href="#main">Skip to release history</a>
  <header class="release-site-header">
    <a class="brand" href="/">MultiAgent<wbr>Memory.com</a>
    <nav class="release-desktop-navigation" aria-label="Primary">
      <a href="/">Home</a>
      <a href="/docs/how-it-works.html">How It Works</a>
      <a href="/docs/api-reference.html">API Reference</a>
      <a href="/docs/memory-boundary.html">Memory Boundary</a>
      <a href="/releases/" aria-current="page">Releases</a>
      <a href="https://github.com/MichaelKappel/Multi-Agent-Memory">GitHub Repo</a>
    </nav>
    <details class="release-mobile-navigation">
      <summary aria-label="Menu">Menu</summary>
      <nav aria-label="Mobile primary">
        <a href="/">Home</a>
        <a href="/docs/how-it-works.html">How It Works</a>
        <a href="/docs/api-reference.html">API Reference</a>
        <a href="/docs/memory-boundary.html">Memory Boundary</a>
        <a href="/releases/" aria-current="page">Releases</a>
        <a href="https://github.com/MichaelKappel/Multi-Agent-Memory">GitHub Repo</a>
      </nav>
    </details>
  </header>
  <main id="main" class="release-page">
    <nav class="breadcrumbs" aria-label="Breadcrumb">
      <a href="/">Home</a>
      <span aria-hidden="true">/</span>
      <span aria-current="page">Release history</span>
    </nav>

    <section class="release-hero" aria-labelledby="release-title">
      <div class="release-hero-copy">
        <p class="eyebrow">Production release history</p>
        <h1 id="release-title">What shipped, when, and from which exact source.</h1>
        <p class="release-lede">This page separates public-edition source releases from production-activated MultiAgentMemory.com website deployments. Each has its own version scope and exact public provenance, so one version can never impersonate the other.</p>
        <div class="actions" aria-label="Release history actions">
          <a class="button primary" href="/releases.json">Read the machine ledger</a>
          <a class="button" href="https://github.com/MichaelKappel/Multi-Agent-Memory">Inspect the source repository</a>
          <a class="button" href="/docs/how-it-works.html">Understand the system</a>
        </div>
      </div>
      <aside class="release-status" aria-labelledby="ledger-status-title">
        <p class="release-status-label" id="ledger-status-title">Ledger status</p>
        <p class="release-status-value"><span class="status-dot" aria-hidden="true"></span>Public edition {current_public_edition}</p>
        <dl class="release-facts">
          <div>
            <dt>Current public edition</dt>
            <dd>{current_public_edition}</dd>
          </div>
          <div>
            <dt>Current website version</dt>
            <dd>{current_display}</dd>
          </div>
          <div>
            <dt>Verified releases</dt>
            <dd>{payload["releaseCount"]}</dd>
          </div>
          <div>
            <dt>Latest activation</dt>
            <dd>{latest_display}</dd>
          </div>
        </dl>
      </aside>
    </section>

    <section class="release-ledger" aria-labelledby="public-edition-heading" data-public-edition-ledger>
      <div class="section-heading">
        <p class="eyebrow">Free reference implementation</p>
        <h2 id="public-edition-heading">Public edition releases</h2>
        <p>These records version the free, single-organization source edition. Each entry links to the immutable Git commit that establishes that release identity.</p>
      </div>
{public_edition_records}
    </section>

    <section class="release-ledger" aria-labelledby="release-ledger-heading" data-release-ledger>
      <div class="section-heading">
        <p class="eyebrow">Verified deployment chronology</p>
        <h2 id="release-ledger-heading">Website deployments</h2>
        <p>These records version the static MultiAgentMemory.com website itself. They appear only after an exact package, source tag, activation date, readback, and live-byte verification succeed.</p>
      </div>
{records}
    </section>

    <section class="release-policy" aria-labelledby="evidence-bar-title">
      <div class="section-heading">
        <p class="eyebrow">Publication standard</p>
        <h2 id="evidence-bar-title">The evidence bar for every entry</h2>
        <p>Each record must answer the questions a user, operator, or auditor needs without exposing private deployment details.</p>
      </div>
      <ol class="release-policy-grid">
        <li><span class="policy-number" aria-hidden="true">01</span><h3>Exact identity</h3><p>A three-part website semantic version and one production activation date.</p></li>
        <li><span class="policy-number" aria-hidden="true">02</span><h3>User-visible change</h3><p>Plain-language changes and milestones that describe what people can actually use.</p></li>
        <li><span class="policy-number" aria-hidden="true">03</span><h3>Separate scopes</h3><p>Website, endpoint API, schema, and package identities stay distinct instead of borrowing one version label.</p></li>
        <li><span class="policy-number" aria-hidden="true">04</span><h3>Public evidence</h3><p>Version-bound, public-safe links support the record. Private paths, credentials, payloads, and internal identifiers never do.</p></li>
      </ol>
    </section>

    <section class="version-scope-section" aria-labelledby="version-scope-title">
      <div class="section-heading">
        <p class="eyebrow">Version clarity</p>
        <h2 id="version-scope-title">One release can have several version scopes</h2>
        <p>The label beside a number matters. These identities are related only when a verified release record explicitly binds them.</p>
      </div>
      <dl class="version-scope-grid">
        <div><dt>Website version</dt><dd>The semantic version assigned to an activated MultiAgentMemory.com static-site release.</dd></div>
        <div><dt>Endpoint API version</dt><dd>Owned by the separately deployed MemoryEndpoints.com runtime; this companion site never inherits it.</dd></div>
        <div><dt>Ledger schema version</dt><dd>Describes the <a href="/releases.json"><code>releases.json</code></a> document contract. It is not the website version.</dd></div>
        <div><dt>Package or source identity</dt><dd>A repository revision or deploy artifact is evidence input, not a public website version by itself.</dd></div>
      </dl>
    </section>

    <section class="release-machine-callout" aria-labelledby="machine-ledger-title">
      <div>
        <p class="eyebrow">For agents and tooling</p>
        <h2 id="machine-ledger-title">The same truth is available as deterministic JSON.</h2>
        <p><code>/releases.json</code> reports the record policy, version-scope meanings, current production website version, release count, and deployed records. Its schema version is explicitly separate from the website version.</p>
      </div>
      <a class="button primary" href="/releases.json">Open releases.json</a>
    </section>
  </main>
  <footer>
    <p>Source: <a href="https://github.com/MichaelKappel/Multi-Agent-Memory">MichaelKappel/Multi-Agent-Memory</a>. Endpoint: <a href="https://memoryendpoints.com">MemoryEndpoints.com</a>. <a href="/releases/">Production release history</a>.</p>
  </footer>
</body>
</html>
"""


def _manifest_projection(current, payload):
    projected = dict(current)
    latest = payload["releases"][0] if payload["releases"] else None
    release_history = {
        "human": CANONICAL_URL,
        "machine": MACHINE_URL,
        "productionActivatedOnly": True,
        "activationDateMustEqualSuccessfulUploadUtcDate": True,
        "sourceCandidatesPublished": False,
        "currentProductionWebsiteVersion": payload["currentProductionWebsiteVersion"],
        "releaseCount": payload["releaseCount"],
    }
    if latest:
        release_history.update(
            {
                "latestActivationDate": latest["activationDate"],
                "activationTimezone": latest["activationTimezone"],
                "latestReleaseStatus": latest["status"],
                "sourceTag": next(
                    item["url"]
                    for item in latest["evidence"]
                    if item["type"] == "source_tag"
                ),
            }
        )
    projected["releaseHistory"] = release_history
    edition_history = payload["publicEditionHistory"]
    current_edition = next(
        item
        for item in edition_history["releases"]
        if item["version"] == edition_history["currentVersion"]
    )
    projected["publicEdition"] = {
        "currentVersion": edition_history["currentVersion"],
        "latestReleaseDate": current_edition["releaseDate"],
        "releaseCount": edition_history["releaseCount"],
        "exactSourceCommit": current_edition["evidence"][0]["commitSha"],
        "releaseHistory": CANONICAL_URL,
        "machineLedger": MACHINE_URL,
    }
    return json.dumps(projected, indent=2, ensure_ascii=False) + "\n"


def _llms_projection(payload):
    latest = payload["releases"][0] if payload["releases"] else None
    edition = payload["publicEditionHistory"]
    current_edition = next(
        item
        for item in edition["releases"]
        if item["version"] == edition["currentVersion"]
    )
    lines = [
        "Production release history:",
        "",
        f"- Current public edition: {edition['currentVersion']}.",
        f"- Current public edition release date: {current_edition['releaseDate']} (UTC).",
        f"- Verified public edition release count: {edition['releaseCount']}.",
        f"- Current public edition exact source: {current_edition['evidence'][0]['url']}",
        f"- Current production website version: {payload['currentProductionWebsiteVersion'] or 'not established'}.",
        f"- Verified production release count: {payload['releaseCount']}.",
        f"- Human history: {CANONICAL_URL}",
        f"- Machine ledger: {MACHINE_URL}",
    ]
    if latest:
        source_tag = next(
            item["url"] for item in latest["evidence"] if item["type"] == "source_tag"
        )
        lines.extend(
            [
                f"- Latest production activation: {latest['activationDate']} ({latest['activationTimezone']}).",
                f"- Latest release status: {latest['status']}.",
                f"- Latest release: {latest['title']}.",
                f"- Public source evidence: {source_tag}",
            ]
        )
    lines.extend(
        [
            "- The ledger includes only production-activated website releases with an exact semantic version, revision-bound activation date, and public-safe evidence.",
            "- Source candidates, planned work, and package attempts are excluded.",
            "- Website, MemoryEndpoints.com API, release-ledger schema, and repository/package identities are separate version scopes.",
            "- Public-edition and website-deployment versions are separate scopes even when one release updates both surfaces.",
        ]
    )
    return "\n".join(lines)


def _replace_llms_section(current, payload):
    start = "Production release history:\n"
    end = "\nMemory boundary:\n"
    _require(
        start in current and end in current,
        "llms.txt release projection boundary is missing",
    )
    prefix, remainder = current.split(start, 1)
    _old, suffix = remainder.split(end, 1)
    return prefix + _llms_projection(payload) + "\n\nMemory boundary:\n" + suffix


def _ai_projection(payload):
    latest = payload["releases"][0] if payload["releases"] else None
    edition = payload["publicEditionHistory"]
    current_edition = next(
        item
        for item in edition["releases"]
        if item["version"] == edition["currentVersion"]
    )
    lines = [
        "Production release history:",
        f"Current public edition: {edition['currentVersion']}.",
        f"Current public edition release date: {current_edition['releaseDate']} (UTC).",
        f"Verified public edition release count: {edition['releaseCount']}.",
        f"Current public edition exact source: {current_edition['evidence'][0]['url']}",
        f"Current production website version: {payload['currentProductionWebsiteVersion'] or 'not established'}.",
        f"Verified production release count: {payload['releaseCount']}.",
        f"Human history: {CANONICAL_URL}",
        f"Machine ledger: {MACHINE_URL}",
    ]
    if latest:
        source_tag = next(
            item["url"] for item in latest["evidence"] if item["type"] == "source_tag"
        )
        lines.extend(
            [
                f"Latest production activation: {latest['activationDate']} ({latest['activationTimezone']}).",
                f"Latest release status: {latest['status']}.",
                f"Latest release: {latest['title']}.",
                f"Public source evidence: {source_tag}",
            ]
        )
    lines.append(
        "Policy: website records are deployed-only; public-edition records require exact immutable source commits; source candidates, plans, and package attempts stay out; version scopes remain separate."
    )
    return "\n".join(lines) + "\n"


def _replace_ai_section(current, payload):
    start = "Production release history:\n"
    old = "The public release ledger is deployed-only."
    if start in current:
        prefix = current.split(start, 1)[0].rstrip()
    else:
        _require(old in current, "ai.txt release projection boundary is missing")
        prefix = current.split(old, 1)[0].rstrip()
    return prefix + "\n\n" + _ai_projection(payload)


def _readme_projection(current, payload):
    marker = "- The public production release ledger records only "
    lines = current.splitlines()
    indexes = [index for index, line in enumerate(lines) if line.startswith(marker)]
    _require(len(indexes) == 1, "README release projection boundary is missing")
    current_version = payload["currentProductionWebsiteVersion"] or "not established"
    lines[indexes[0]] = (
        "- The public production release ledger records only evidence-bound deployments. "
        f"Its current website version is `{current_version}` with {payload['releaseCount']} verified release"
        f"{'s' if payload['releaseCount'] != 1 else ''}; source candidates, plans, and package attempts stay excluded."
    )
    return "\n".join(lines) + "\n"


def project_release_surfaces(source_files, payload):
    """Project exact public surfaces from an in-memory path-to-bytes mapping."""
    try:
        manifest = json.loads(source_files["ai-manifest.json"].decode("utf-8"))
        llms = (
            source_files["llms.txt"]
            .decode("utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        ai = (
            source_files["ai.txt"]
            .decode("utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
        readme = (
            source_files["README.md"]
            .decode("utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseProjectionError(
            "a release projection target is unavailable or invalid"
        ) from exc
    return {
        "releases/index.html": render_release_html(payload).encode("utf-8"),
        "ai-manifest.json": _manifest_projection(manifest, payload).encode("utf-8"),
        "llms.txt": _replace_llms_section(llms, payload).encode("utf-8"),
        "ai.txt": _replace_ai_section(ai, payload).encode("utf-8"),
        "README.md": _readme_projection(readme, payload).encode("utf-8"),
    }


def projected_files(site_root, payload):
    site_root = Path(site_root)
    source_paths = ("ai-manifest.json", "llms.txt", "ai.txt", "README.md")
    try:
        source_files = {
            relative: (site_root / relative).read_bytes() for relative in source_paths
        }
    except OSError as exc:
        raise ReleaseProjectionError(
            "a release projection target is unavailable or invalid"
        ) from exc
    return {
        site_root / relative: expected
        for relative, expected in project_release_surfaces(
            source_files, payload
        ).items()
    }


def projection_drift(site_root=DEFAULT_SITE_ROOT):
    site_root = Path(site_root)
    payload = load_ledger(site_root)
    drift = []
    for path, expected in projected_files(site_root, payload).items():
        try:
            actual = path.read_bytes()
        except OSError:
            actual = None
        if actual != expected:
            drift.append(str(path.relative_to(site_root)).replace("\\", "/"))
    return payload, drift


def _write_projections(site_root, payload):
    for path, expected in projected_files(site_root, payload).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != expected:
            path.write_bytes(expected)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-root", default=str(DEFAULT_SITE_ROOT))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")
    site_root = Path(args.site_root)
    try:
        payload = load_ledger(site_root)
        if args.write:
            _write_projections(site_root, payload)
        payload, drift = projection_drift(site_root)
        ledger_bytes = (site_root / "releases.json").read_bytes()
        report = {
            "schemaVersion": "multiagentmemory.release_projection.v1",
            "ok": not drift,
            "mode": "write" if args.write else "check",
            "currentProductionWebsiteVersion": payload[
                "currentProductionWebsiteVersion"
            ],
            "releaseCount": payload["releaseCount"],
            "ledgerSha256": hashlib.sha256(ledger_bytes).hexdigest(),
            "projectedFileCount": 5,
            "driftFiles": drift,
            "valuesRedacted": True,
        }
    except ReleaseProjectionError as exc:
        report = {
            "schemaVersion": "multiagentmemory.release_projection.v1",
            "ok": False,
            "mode": "write" if args.write else "check",
            "error": str(exc),
            "driftFiles": [],
            "valuesRedacted": True,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
