"""分析包可复现性、发布适配与服务门面测试。"""

import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from researchmesh.contracts import MeshError
from researchmesh.network import (
    FixedDictionary,
    NetworkConfig,
    save_bundle,
    load_bundle,
    verify_bundle,
    rerun_bundle,
)
from researchmesh.network.adapter import work_table_from_release
from researchmesh.network.service import NetworkAnalytics


def rows():
    return [
        {
            "record_key": "lab:1",
            "work_id": "w1",
            "source": "lab",
            "year": 2024,
            "institutions": ["A", "B"],
            "active": True,
        },
        {
            "record_key": "lab:2",
            "work_id": "w2",
            "source": "lab",
            "year": 2024,
            "institutions": ["B", "C"],
            "active": True,
        },
    ]


def config(sources=None):
    return NetworkConfig(
        release="r1", year_from=2020, year_to=2026,
        weight_scheme="fractional", seed=7, sources=sources,
        dictionary_revision=1,
    )


class BundleTests(unittest.TestCase):
    def test_save_reload_and_rerun_match_exactly(self):
        dictionary = FixedDictionary({"a2": "a"}, revision=1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bundle.json"
            written = save_bundle(
                path, "r1", "release-digest", rows(), dictionary, config(),
                notes="unit test",
            )
            self.assertTrue(path.exists())
            loaded = load_bundle(path)
            self.assertEqual(loaded["bundle_digest"], written["bundle_digest"])
            report = verify_bundle(loaded)
            self.assertTrue(report["verified"])
            rerun = rerun_bundle(path)
            self.assertEqual(
                rerun["result"]["communities_result"]["partition"],
                loaded["result"]["communities_result"]["partition"],
            )
            self.assertEqual(
                rerun["result"]["network_digest"],
                loaded["result"]["network_digest"],
            )

    def test_tampering_is_detected(self):
        dictionary = FixedDictionary(revision=1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bundle.json"
            save_bundle(path, "r1", "d", rows(), dictionary, config())
            payload = json.loads(path.read_text("utf-8"))
            payload["config"]["seed"] = 999
            path.write_text(json.dumps(payload, sort_keys=True), "utf-8")
            with self.assertRaises(MeshError) as caught:
                load_bundle(path)
            self.assertEqual(caught.exception.code, "integrity")

    def test_input_change_breaks_network_digest(self):
        dictionary = FixedDictionary(revision=1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bundle.json"
            save_bundle(path, "r1", "d", rows(), dictionary, config())
            payload = json.loads(path.read_text("utf-8"))
            # 改一条边权重输入（机构 C -> D），但保留外层摘要以模拟重算场景。
            payload["work_table"][1]["institutions"] = ["B", "D"]
            from researchmesh.network.bundle import rerun_payload
            rerun = rerun_payload(payload)
            self.assertNotEqual(
                rerun["network_digest"],
                payload["result"]["network_digest"],
            )


class AdapterTests(unittest.TestCase):
    def _release(self):
        return {
            "format_version": 1,
            "masters": [
                {
                    "id": "lab:1",
                    "members": ["lab:1", "extra:1"],
                    "data": {"year": 2024},
                },
            ],
        }

    def test_builds_one_row_per_source_record(self):
        table = work_table_from_release(
            self._release(),
            {"lab:1": ["A", "B"], "extra:1": ["A", "B"]},
        )
        self.assertEqual(len(table["rows"]), 2)
        self.assertEqual({row["work_id"] for row in table["rows"]}, {"lab:1"})
        self.assertEqual(table["identity_conflicts"], [])

    def test_conflicting_institution_sets_flagged(self):
        table = work_table_from_release(
            self._release(),
            {"lab:1": ["A", "B"], "extra:1": ["A", "C"]},
        )
        self.assertEqual(len(table["identity_conflicts"]), 1)

    def test_missing_member_mapping_rejected(self):
        with self.assertRaises(MeshError):
            work_table_from_release(self._release(), {"lab:1": ["A", "B"]})


class FacadeTests(unittest.TestCase):
    def test_analyze_table_without_backend(self):
        analytics = NetworkAnalytics()
        result = analytics.analyze_table(
            rows(), config(), FixedDictionary(revision=1)
        )
        self.assertEqual(result["totals"]["edge_count"], 2)
        self.assertIn("communities_result", result)

    def test_release_table_requires_backend(self):
        with self.assertRaises(MeshError):
            NetworkAnalytics().release_table("r1", {})


if __name__ == "__main__":
    unittest.main()
