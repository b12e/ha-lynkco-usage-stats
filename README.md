# ha_lynkco_2025 usage stats

Collects Home Assistant usage statistics for the
[`ha_lynkco_2025`](https://github.com/b12e/ha_lynkco_2025) custom integration and
publishes a small JSON report with installs per version and a combined total.

## How it works

1. Fetches the public HA analytics dump:
   <https://analytics.home-assistant.io/custom_integrations.json>
2. Builds a **version whitelist** from the published releases of
   `b12e/ha_lynkco_2025` (release tags, with the leading `v` stripped).
3. Looks up the `lynkco` entry in the analytics dump and keeps only the versions
   that are in the whitelist.

The whitelist step is important: the `lynkco` analytics domain is **shared** with
an older, unrelated integration. That older integration's versions (the `1.x`
series) are reported under the same key and must be excluded — only versions
actually released from this repo count.

## Output

[`usage.json`](usage.json), regenerated on every run:

```json
{
  "generated_at": "...",
  "domain": "lynkco",
  "source_repo": "b12e/ha_lynkco_2025",
  "usage_per_version": { "0.5.2": 7, "0.2.6": 1, "0.5.0": 1 },
  "total_usage": 9
}
```

- `usage_per_version` — installs per whitelisted version that has reported usage.
- `total_usage` — combined installs across the whitelisted versions.

## Running locally

No dependencies — Python 3.12+ standard library only.

```bash
python scripts/collect_usage.py            # prints JSON to stdout
OUTPUT_FILE=usage.json python scripts/collect_usage.py   # also writes the file
```

Set `GITHUB_TOKEN` to avoid GitHub API rate limits when fetching releases.

## Automation

[`.github/workflows/collect-usage.yml`](.github/workflows/collect-usage.yml) runs
the collector daily (06:00 UTC) and on manual dispatch. Each run:

- writes the JSON to the workflow **job summary**,
- uploads it as a build **artifact**, and
- commits the refreshed `usage.json` back to `main` if it changed.

## Configuration

Environment variables (with defaults):

| Variable | Default | Purpose |
| --- | --- | --- |
| `RELEASES_REPO` | `b12e/ha_lynkco_2025` | Repo whose releases define the whitelist |
| `INTEGRATION_DOMAIN` | `lynkco` | Key to look up in the analytics dump |
| `OUTPUT_FILE` | _(unset)_ | If set, also write JSON to this path |
| `GITHUB_TOKEN` / `GH_TOKEN` | _(unset)_ | Auth for the GitHub releases API |

> **Version matching is exact** (after stripping `v`). A release tagged `v0.1`
> matches the analytics version `0.1`, not `0.1.0`.
