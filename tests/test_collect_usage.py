"""Tests for scripts/collect_usage.py. Network access is mocked out."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "collect_usage.py"
spec = importlib.util.spec_from_file_location("collect_usage", SCRIPT)
collect_usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect_usage)

ANALYTICS = {
    "lynkco": {
        "total": 82,
        "versions": {"1.12.0": 21, "0.6.1": 32, "1.10.2": 13, "0.5.0": 1},
    },
    "flinx_garage": {
        "total": 25,
        "versions": {"2.4.0": 2, "3.1.1": 17, "3.0.1": 5, "3.1.0": 1},
    },
    "unrelated": {"total": 3, "versions": {"1.0.0": 3}},
}

RELEASES = {
    "b12e/ha_lynkco_2025": [
        {"tag_name": "v0.6.1", "draft": False},
        {"tag_name": "v0.5.0", "draft": False},
        {"tag_name": "v0.7.0", "draft": True},  # drafts are ignored
    ],
    "b12e/flinx-garage-ha": [
        {"tag_name": "v3.1.1", "draft": False},
        {"tag_name": "v3.1.0", "draft": False},
        {"tag_name": "v3.0.1", "draft": False},
        {"tag_name": "v2.4.0", "draft": False},
        {"tag_name": "v2.4.0b1", "draft": False},
    ],
}

INTEGRATIONS = [
    {"domain": "lynkco", "repo": "b12e/ha_lynkco_2025"},
    {"domain": "flinx_garage", "repo": "b12e/flinx-garage-ha"},
]


def fake_fetch_json(url, token=None):
    if url == collect_usage.ANALYTICS_URL:
        return ANALYTICS
    prefix = "https://api.github.com/repos/"
    assert url.startswith(prefix), url
    repo, _, query = url[len(prefix):].partition("/releases?")
    page = int(dict(part.split("=") for part in query.split("&"))["page"])
    return RELEASES.get(repo, []) if page == 1 else []


class NormalizeVersionTests(unittest.TestCase):
    def test_strips_leading_v(self):
        self.assertEqual(collect_usage.normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(collect_usage.normalize_version("V1.2.3"), "1.2.3")
        self.assertEqual(collect_usage.normalize_version("1.2.3"), "1.2.3")


class WhitelistTests(unittest.TestCase):
    def test_paginates_until_short_page(self):
        pages = {
            1: [{"tag_name": f"v1.0.{i}", "draft": False} for i in range(100)],
            2: [{"tag_name": "v2.0.0", "draft": False}],
        }
        calls = []

        def fetch(url, token=None):
            page = int(url.rsplit("page=", 1)[1])
            calls.append(page)
            return pages.get(page, [])

        with mock.patch.object(collect_usage, "fetch_json", fetch):
            versions = collect_usage.get_whitelisted_versions("o/r", None)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(len(versions), 101)
        self.assertIn("2.0.0", versions)


class LoadIntegrationsTests(unittest.TestCase):
    def write(self, data):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.addCleanup(os.unlink, tmp.name)
        json.dump(data, tmp)
        tmp.close()
        return Path(tmp.name)

    def test_loads_configured_list(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = collect_usage.load_integrations(self.write(INTEGRATIONS))
        self.assertEqual(
            result,
            [
                collect_usage.Integration("lynkco", "b12e/ha_lynkco_2025"),
                collect_usage.Integration("flinx_garage", "b12e/flinx-garage-ha"),
            ],
        )

    def test_env_override_selects_single_integration(self):
        env = {"INTEGRATION_DOMAIN": "flinx_garage", "RELEASES_REPO": "b12e/flinx-garage-ha"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = collect_usage.load_integrations(Path("/nonexistent.json"))
        self.assertEqual(result, [collect_usage.Integration("flinx_garage", "b12e/flinx-garage-ha")])

    def test_env_override_requires_both_variables(self):
        with mock.patch.dict(os.environ, {"INTEGRATION_DOMAIN": "x"}, clear=True):
            with self.assertRaises(ValueError):
                collect_usage.load_integrations(self.write(INTEGRATIONS))

    def test_rejects_bad_config(self):
        bad = [
            [],  # empty
            {"domain": "a", "repo": "o/r"},  # not a list
            [{"domain": "Flinx-Garage", "repo": "o/r"}],  # invalid domain
            [{"domain": "ok", "repo": "no-slash"}],  # invalid repo
            [{"domain": "ok", "repo": "o/r"}, {"domain": "ok", "repo": "o/r2"}],  # dup
            [{"repo": "o/r"}],  # missing domain
        ]
        with mock.patch.dict(os.environ, {}, clear=True):
            for data in bad:
                with self.subTest(data=data), self.assertRaises(ValueError):
                    collect_usage.load_integrations(self.write(data))


class BuildReportsTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(collect_usage, "fetch_json", fake_fetch_json)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.integrations = collect_usage._validate_integrations(INTEGRATIONS, "test")

    def test_filters_to_released_versions_and_sums(self):
        with redirect_stderr(io.StringIO()) as err:
            combined, per_integration = collect_usage.build_reports(
                self.integrations, None, "2026-01-01T00:00:00+00:00"
            )

        self.assertEqual(list(per_integration), ["lynkco", "flinx_garage"])
        lynkco = per_integration["lynkco"]
        self.assertEqual(
            lynkco,
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "domain": "lynkco",
                "source_repo": "b12e/ha_lynkco_2025",
                "analytics_source": collect_usage.ANALYTICS_URL,
                "usage_per_version": {"0.6.1": 32, "0.5.0": 1},
                "total_usage": 33,
            },
        )
        # Sorted by install count, descending.
        self.assertEqual(
            list(per_integration["flinx_garage"]["usage_per_version"]),
            ["3.1.1", "3.0.1", "2.4.0", "3.1.0"],
        )
        self.assertEqual(per_integration["flinx_garage"]["total_usage"], 25)

        self.assertEqual(combined["total_usage"], 58)
        self.assertEqual(list(combined["integrations"]), ["lynkco", "flinx_garage"])
        self.assertEqual(combined["integrations"]["lynkco"]["total_usage"], 33)
        self.assertEqual(combined["integrations"]["flinx_garage"]["total_usage"], 25)
        self.assertNotIn("domain", combined["integrations"]["lynkco"])
        # The shared-domain 1.x versions are reported as ignored.
        self.assertIn("1.10.2, 1.12.0", err.getvalue())

    def test_unknown_domain_and_no_releases_warn_but_do_not_fail(self):
        integrations = [collect_usage.Integration("missing", "nobody/nothing")]
        with redirect_stderr(io.StringIO()) as err:
            combined, per_integration = collect_usage.build_reports(integrations, None, "t")
        self.assertEqual(per_integration["missing"]["usage_per_version"], {})
        self.assertEqual(combined["total_usage"], 0)
        self.assertIn("no releases found for nobody/nothing", err.getvalue())
        self.assertIn("'missing' not present in analytics dump", err.getvalue())


class MainTests(unittest.TestCase):
    def test_writes_per_integration_and_combined_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = tmp / "integrations.json"
            config.write_text(json.dumps(INTEGRATIONS))
            env = {
                "OUTPUT_DIR": str(tmp / "usage"),
                "OUTPUT_FILE": str(tmp / "usage.json"),
            }
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
                collect_usage, "fetch_json", fake_fetch_json
            ), mock.patch.object(collect_usage, "INTEGRATIONS_FILE", config), redirect_stdout(
                io.StringIO()
            ) as out, redirect_stderr(io.StringIO()):
                self.assertEqual(collect_usage.main(), 0)

            combined = json.loads((tmp / "usage.json").read_text())
            self.assertEqual(json.loads(out.getvalue()), combined)
            self.assertEqual(combined["total_usage"], 58)
            self.assertEqual(sorted(p.name for p in (tmp / "usage").iterdir()), ["flinx_garage.json", "lynkco.json"])
            flinx = json.loads((tmp / "usage" / "flinx_garage.json").read_text())
            self.assertEqual(flinx["domain"], "flinx_garage")
            self.assertEqual(flinx["total_usage"], 25)
            self.assertEqual(flinx["generated_at"], combined["generated_at"])
            # Files end with a trailing newline, like the previous single-file output.
            self.assertTrue((tmp / "usage.json").read_text().endswith("}\n"))

    def test_no_files_written_without_output_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "integrations.json"
            config.write_text(json.dumps(INTEGRATIONS))
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                collect_usage, "fetch_json", fake_fetch_json
            ), mock.patch.object(collect_usage, "INTEGRATIONS_FILE", config), redirect_stdout(
                io.StringIO()
            ), redirect_stderr(io.StringIO()):
                self.assertEqual(collect_usage.main(), 0)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["integrations.json"])


if __name__ == "__main__":
    unittest.main()
