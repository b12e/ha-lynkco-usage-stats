# hacs-b12e-usage-stats

Collects Home Assistant usage statistics for b12e's HACS custom integrations and
publishes small JSON reports with installs per version and totals.

## Tracked integrations

| Analytics domain | Repository | Report |
| --- | --- | --- |
| `lynkco` | [`b12e/ha_lynkco_2025`](https://github.com/b12e/ha_lynkco_2025) | [`usage/lynkco.json`](usage/lynkco.json) |
| `flinx_garage` | [`b12e/flinx-garage-ha`](https://github.com/b12e/flinx-garage-ha) | [`usage/flinx_garage.json`](usage/flinx_garage.json) |

The list lives in [`integrations.json`](integrations.json).

## How it works

For every integration in `integrations.json` the collector:

1. Fetches the public HA analytics dump:
   <https://analytics.home-assistant.io/custom_integrations.json>
2. Builds a **version whitelist** from the published releases of the
   integration's repository (release tags, with the leading `v` stripped).
3. Looks up the integration's domain in the analytics dump and keeps only the
   versions that are in the whitelist.

The whitelist step is important: an analytics domain can be **shared** with an
unrelated integration. The `lynkco` domain, for example, is also used by an older
integration whose versions (the `1.x` series) are reported under the same key and
must be excluded. Only versions actually released from the configured repo count.

## Output

Every run regenerates one report per integration plus a combined report.

### Per integration: `usage/<domain>.json`

```json
{
  "generated_at": "...",
  "domain": "flinx_garage",
  "source_repo": "b12e/flinx-garage-ha",
  "analytics_source": "https://analytics.home-assistant.io/custom_integrations.json",
  "usage_per_version": { "3.1.1": 17, "3.0.1": 5, "2.4.0": 2, "3.1.0": 1 },
  "total_usage": 25
}
```

- `usage_per_version` — installs per whitelisted version that has reported usage.
- `total_usage` — combined installs across the whitelisted versions.

### Combined: [`usage.json`](usage.json)

```json
{
  "generated_at": "...",
  "analytics_source": "https://analytics.home-assistant.io/custom_integrations.json",
  "integrations": {
    "lynkco": {
      "source_repo": "b12e/ha_lynkco_2025",
      "usage_per_version": { "0.6.1": 32, "0.5.0": 1 },
      "total_usage": 33
    },
    "flinx_garage": {
      "source_repo": "b12e/flinx-garage-ha",
      "usage_per_version": { "3.1.1": 17, "3.0.1": 5, "2.4.0": 2, "3.1.0": 1 },
      "total_usage": 25
    }
  },
  "total_usage": 58
}
```

Here `total_usage` at the top level is the sum over **all** integrations.

## Badges

Point a [shields.io dynamic JSON badge](https://shields.io/badges/dynamic-json-badge)
at the per-integration report:

```markdown
![Usage counter](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://raw.githubusercontent.com/b12e/hacs-b12e-usage-stats/refs/heads/main/usage/flinx_garage.json&query=$.total_usage)
```

Swap `flinx_garage.json` for `lynkco.json` (or any other tracked domain) as needed.

> **Note:** The badge in `b12e/ha_lynkco_2025` currently reads `$.total_usage` from
> the root `usage.json`. That value is now the total across all integrations, so the
> badge should be repointed to `usage/lynkco.json`.

## Adding an integration

1. Add an entry to `integrations.json`:

   ```json
   { "domain": "<analytics domain>", "repo": "<owner>/<repo>" }
   ```

   `domain` is the key the integration reports under in the analytics dump (the
   integration's `manifest.json` domain). `repo` is the GitHub repository whose
   published releases define the version whitelist.

2. Commit to `main`. The workflow runs on changes to `integrations.json` and
   creates `usage/<domain>.json` on its next run.

Removing an integration from the list does not delete its report file; remove
`usage/<domain>.json` by hand.

## Running locally

No dependencies — Python 3.12+ standard library only.

```bash
python scripts/collect_usage.py                                  # prints the combined JSON to stdout
OUTPUT_DIR=usage OUTPUT_FILE=usage.json python scripts/collect_usage.py   # also writes the files
```

Set `GITHUB_TOKEN` to avoid GitHub API rate limits when fetching releases.

To check a single integration without editing `integrations.json`:

```bash
INTEGRATION_DOMAIN=flinx_garage RELEASES_REPO=b12e/flinx-garage-ha python scripts/collect_usage.py
```

Tests (standard library `unittest`, no network access needed):

```bash
python -m unittest discover -s tests -v
```

## Automation

[`.github/workflows/collect-usage.yml`](.github/workflows/collect-usage.yml) runs
the collector daily (06:00 UTC), on manual dispatch, and on pushes to `main` that
touch the collector, the workflow or `integrations.json`. Each run:

- writes the combined JSON to the workflow **job summary**,
- uploads `usage.json` and `usage/` as a build **artifact**, and
- commits the refreshed reports back to `main` if anything changed.

## Configuration

Environment variables (with defaults):

| Variable | Default | Purpose |
| --- | --- | --- |
| `INTEGRATIONS_FILE` | `integrations.json` | List of `{domain, repo}` entries to collect |
| `OUTPUT_DIR` | _(unset)_ | If set, write `<domain>.json` per integration here |
| `OUTPUT_FILE` | _(unset)_ | If set, write the combined JSON to this path |
| `INTEGRATION_DOMAIN` + `RELEASES_REPO` | _(unset)_ | If both set, collect only this one integration instead of the list |
| `GITHUB_TOKEN` / `GH_TOKEN` | _(unset)_ | Auth for the GitHub releases API |

> **Version matching is exact** (after stripping `v`). A release tagged `v0.1`
> matches the analytics version `0.1`, not `0.1.0`.
