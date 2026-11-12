"""网络分析与研合发布流程的端到端集成测试。"""

import unittest

from researchmesh.service import ResearchMesh
from researchmesh.network import FixedDictionary, NetworkConfig
from researchmesh.network.service import NetworkAnalytics


def achievement(institution, year, registry):
    return {
        "title": "synthetic achievement " + registry,
        "institution": institution,
        "kind": "prototype",
        "year": year,
        "identifiers": {"registry": [registry]},
    }


class ReleaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.mesh = ResearchMesh()
        self.addCleanup(self.mesh.close)
        self.mesh.sources.register("lab", "Laboratory", 10)
        self.records = [
            {"id": "w1", "data": achievement("A; B", 2025, "local:w1")},
            {"id": "w2", "data": achievement("B; C", 2025, "local:w2")},
            {"id": "w3", "data": achievement("D; E", 2025, "local:w3")},
            {"id": "bridge", "data": achievement("C; D", 2025, "local:bridge")},
        ]
        self.mesh.sources.snapshot("lab-1", "lab", 1, self.records, 0)
        preview = self.mesh.releases.preview()
        self.mesh.releases.freeze("rel-1", preview["digest"], "publisher")
        # 结构化机构名单（显式提供，不从自由文本猜分隔符）。
        self.members = {
            "lab:w1": ["A", "B"],
            "lab:w2": ["B", "C"],
            "lab:w3": ["D", "E"],
            "lab:bridge": ["C", "D"],
        }

    def test_analytics_reads_frozen_release(self):
        table = self.mesh.analytics.release_table("rel-1", self.members)
        self.assertEqual(len(table["rows"]), 4)
        result = self.mesh.analytics.analyze_release(
            "rel-1", self.members, 2024, 2026,
            weight_scheme="fractional", seed=7,
        )
        # 桥边把 5 个机构连成一个分量，但模块度优化得到两个社区。
        self.assertEqual(result["component_count"], 1)
        self.assertEqual(result["community_count"], 2)
        self.assertFalse(result["components_equal_communities"])
        partition = result["communities_result"]["partition"]
        self.assertNotEqual(partition["c"], partition["d"])
        self.assertEqual(partition["a"], partition["b"])
        self.assertEqual(partition["d"], partition["e"])

    def test_actions_are_registered_for_dispatch(self):
        actions = self.mesh.actions()
        for name in [
            "network.release_table",
            "network.analyze_release",
            "network.analyze_table",
            "network.compare_releases",
            "network.export_bundle",
            "network.verify_bundle_file",
            "network.rerun_bundle_file",
        ]:
            self.assertIn(name, actions)

    def test_fixed_dictionary_merges_alias_in_network(self):
        # 通过服务门面用显式词典把 A2 并入 A。
        analytics = NetworkAnalytics(self.mesh)
        members = dict(self.members)
        members["lab:w1"] = ["A2", "B"]
        dictionary = FixedDictionary({"a2": "a"}, revision=1)
        config = NetworkConfig(
            release="rel-1", year_from=2024, year_to=2026, seed=7,
            dictionary_revision=1,
        )
        table = analytics.release_table("rel-1", members)
        result = analytics.analyze_table(table["rows"], config, dictionary)
        node_ids = {node["id"] for node in result["nodes"]}
        self.assertIn("a", node_ids)
        self.assertNotIn("a2", node_ids)

    def test_dictionary_from_live_store(self):
        self.mesh.dictionary.put(
            "institution", "A2", "A", 0, "same organization"
        )
        self.mesh.sources.reindex(1)
        dictionary = self.mesh.analytics._dictionary()
        self.assertEqual(dictionary.resolve("a2"), "a")


if __name__ == "__main__":
    unittest.main()
