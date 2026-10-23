#!/usr/bin/env python3
"""Collect Home Assistant usage statistics for b12e's HACS integrations.

For every integration listed in ``integrations.json`` this fetches the public
Home Assistant analytics dump and the release list of the integration's GitHub
repo, then reports installation counts for *only* the versions that were
actually published as releases of that repo.

This whitelist matters because an analytics domain can be shared with another,
unrelated integration. The ``lynkco`` domain, for example, is also used by an
older integration whose versions (the 1.x series) must be excluded.

Outputs:
  * one JSON report per integration, ``<OUTPUT_DIR>/<domain>.json``, with usage
    per whitelisted version and that integration's total, and
  * one combined JSON report, ``OUTPUT_FILE``, covering all integrations.

The combined report is always printed to stdout. Files are only written when
the corresponding environment variable is set.

No third-party dependencies — standard library only.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ANALYTICS_URL = "https://analytics.home-assistant.io/custom_integrations.json"
USER_AGENT = "hacs-b12e-usage-stats"
REPO_ROOT = Path(__file__).resolve().parent.parent
# List of integrations to track: [{"domain": ..., "repo": ...}, ...]
INTEGRATIONS_FILE = Path(
    os.environ.get("INTEGRATIONS_FILE", REPO_ROOT / "integrations.json")
)
# Home Assistant integration domains are lowercase snake_case; the domain also
# becomes the per-integration output file name, so keep it strict.
DOMAIN_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class Integration:
    domain: str  # key under which the integration appears in the analytics dump
    repo: str  # GitHub repo (owner/name) whose releases define the whitelist


def log(message: str) -> None:
    print(message, file=sys.stderr)


def fetch_json(url: str, token: str | None = None) -> object:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def normalize_version(tag: str) -> str:
    """Strip a leading 'v' so release tags match analytics version strings."""
    return tag[1:] if tag.startswith(("v", "V")) else tag


def get_whitelisted_versions(repo: str, token: str | None) -> set[str]:
    """Return normalized version strings for all published (non-draft) releases."""
    versions: set[str] = set()
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
        releases = fetch_json(url, token)
        if not releases:
            break
        for rel in releases:
            if rel.get("draft"):
                continue
            versions.add(normalize_version(rel["tag_name"]))
        if len(releases) < 100:
            break
        page += 1
    return versions


def load_integrations(path: Path = INTEGRATIONS_FILE) -> list[Integration]:
    """Return the integrations to collect.

    Setting both ``INTEGRATION_DOMAIN`` and ``RELEASES_REPO`` selects a single
    integration instead of the configured list (handy for ad-hoc checks).
    """
    domain = os.environ.get("INTEGRATION_DOMAIN")
    repo = os.environ.get("RELEASES_REPO")
    if domain or repo:
        if not (domain and repo):
            raise ValueError("INTEGRATION_DOMAIN and RELEASES_REPO must be set together")
        return _validate_integrations([{"domain": domain, "repo": repo}], "environment")

    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return _validate_integrations(raw, str(path))


def _validate_integrations(raw: object, source: str) -> list[Integration]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{source}: expected a non-empty list of integrations")
    integrations: list[Integration] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{source}: entry {index} must be an object")
        domain = item.get("domain")
        repo = item.get("repo")
        if not isinstance(domain, str) or not DOMAIN_RE.match(domain):
            raise ValueError(
                f"{source}: entry {index} has an invalid 'domain' {domain!r} "
                "(expected lowercase letters, digits and underscores)"
            )
        if not isinstance(repo, str) or repo.count("/") != 1 or not all(repo.split("/")):
            raise ValueError(
                f"{source}: entry {index} has an invalid 'repo' {repo!r} (expected owner/name)"
            )
        if domain in seen:
            raise ValueError(f"{source}: duplicate domain {domain!r}")
        seen.add(domain)
        integrations.append(Integration(domain=domain, repo=repo))
    return integrations


def collect_integration(
    integration: Integration, analytics: dict, token: str | None
) -> tuple[dict[str, int], int]:
    """Return (usage per whitelisted version, total) for one integration."""
    whitelist = get_whitelisted_versions(integration.repo, token)
    if not whitelist:
        log(f"warning: no releases found for {integration.repo}")

    entry = analytics.get(integration.domain)
    if entry is None:
        log(f"warning: domain {integration.domain!r} not present in analytics dump")
    all_versions: dict[str, int] = (entry or {}).get("versions", {})

    usage_per_version = {
        version: count
        for version, count in all_versions.items()
        if version in whitelist
    }
    excluded = sorted(set(all_versions) - whitelist)
    if excluded:
        log(
            f"{integration.domain}: ignoring {len(excluded)} version(s) not released "
            f"from {integration.repo}: {', '.join(excluded)}"
        )

    ordered = dict(sorted(usage_per_version.items(), key=lambda kv: kv[1], reverse=True))
    return ordered, sum(ordered.values())


def build_reports(
    integrations: list[Integration], token: str | None, generated_at: str
) -> tuple[dict, dict[str, dict]]:
    """Return (combined report, {domain: per-integration report})."""
    analytics = fetch_json(ANALYTICS_URL)
    if not isinstance(analytics, dict):
        raise ValueError("analytics dump is not a JSON object")

    per_integration: dict[str, dict] = {}
    for integration in integrations:
        usage_per_version, total_usage = collect_integration(integration, analytics, token)
        per_integration[integration.domain] = {
            "generated_at": generated_at,
            "domain": integration.domain,
            "source_repo": integration.repo,
            "analytics_source": ANALYTICS_URL,
            "usage_per_version": usage_per_version,
            "total_usage": total_usage,
        }

    combined = {
        "generated_at": generated_at,
        "analytics_source": ANALYTICS_URL,
        "integrations": {
            domain: {
                "source_repo": report["source_repo"],
                "usage_per_version": report["usage_per_version"],
                "total_usage": report["total_usage"],
            }
            for domain, report in per_integration.items()
        },
        "total_usage": sum(report["total_usage"] for report in per_integration.values()),
    }
    return combined, per_integration


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    integrations = load_integrations()
    generated_at = datetime.now(timezone.utc).isoformat()

    combined, per_integration = build_reports(integrations, token, generated_at)
    print(json.dumps(combined, indent=2))

    out_dir = os.environ.get("OUTPUT_DIR")
    if out_dir:
        for domain, report in per_integration.items():
            write_json(Path(out_dir) / f"{domain}.json", report)

    out_file = os.environ.get("OUTPUT_FILE")
    if out_file:
        write_json(Path(out_file), combined)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(f"error: failed to fetch data: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
