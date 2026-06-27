#!/usr/bin/env python3
"""Collect Home Assistant usage statistics for the ha_lynkco_2025 integration.

Fetches the public Home Assistant analytics dump and the release list of the
integration repo, then reports installation counts for *only* the versions that
were actually published as releases of ha_lynkco_2025.

This whitelist matters because the `lynkco` analytics domain is shared with an
older, separate integration; its versions (e.g. the 1.x series) must be excluded.

Output: a JSON document with usage per whitelisted version and the combined total.
No third-party dependencies — standard library only.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ANALYTICS_URL = "https://analytics.home-assistant.io/custom_integrations.json"
# The key under which the integration appears in the analytics dump.
INTEGRATION_DOMAIN = os.environ.get("INTEGRATION_DOMAIN", "lynkco")
# Repo whose releases define the version whitelist.
RELEASES_REPO = os.environ.get("RELEASES_REPO", "b12e/ha_lynkco_2025")


def fetch_json(url: str, token: str | None = None) -> object:
    headers = {
        "User-Agent": "ha-lynkco-usage-stats",
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


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    whitelist = get_whitelisted_versions(RELEASES_REPO, token)
    if not whitelist:
        print(f"warning: no releases found for {RELEASES_REPO}", file=sys.stderr)

    analytics = fetch_json(ANALYTICS_URL)
    entry = analytics.get(INTEGRATION_DOMAIN) or {}
    all_versions: dict[str, int] = entry.get("versions", {})

    usage_per_version = {
        version: count
        for version, count in all_versions.items()
        if version in whitelist
    }
    total_usage = sum(usage_per_version.values())

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domain": INTEGRATION_DOMAIN,
        "source_repo": RELEASES_REPO,
        "analytics_source": ANALYTICS_URL,
        "usage_per_version": dict(
            sorted(usage_per_version.items(), key=lambda kv: kv[1], reverse=True)
        ),
        "total_usage": total_usage,
    }

    output = json.dumps(result, indent=2)
    print(output)

    out_file = os.environ.get("OUTPUT_FILE")
    if out_file:
        with open(out_file, "w", encoding="utf-8") as fh:
            fh.write(output + "\n")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(f"error: failed to fetch data: {exc}", file=sys.stderr)
        raise SystemExit(1)
