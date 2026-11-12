"""网络建图口径测试：词典归一化、成果去重、权重精确性与排除项。"""

import unittest
from fractions import Fraction

from researchmesh.contracts import MeshError
from researchmesh.network import (
    FixedDictionary,
    NetworkConfig,
    NetworkBuilder,
)
from researchmesh.network.model import parse_work_table
from researchmesh.network.builder import edge_map


def row(source, local, work, year, inst, active=True):
    return {
        "record_key": source + ":" + local,
        "work_id": work,
        "source": source,
        "year": year,
        "institutions": inst,
        "active": active,
    }


class BuilderTests(unittest.TestCase):
    def cfg(self, **kw):
        base = dict(release="r1", year_from=2020, year_to=2026,
                    weight_scheme="count", seed=1)
        base.update(kw)
        return NetworkConfig(**base)

    def test_dictionary_alias_normalization_is_fixed(self):
        dictionary = FixedDictionary({"lab x": "X", "x lab": "X"}, revision=2)
        config = self.cfg()
        network = NetworkBuilder(config, dictionary).build(
            parse_work_table([row("s", "1", "w1", 2024, ["Lab X", "Y"])])
        )
        nodes = {node["id"] for node in network["nodes"]}
        self.assertEqual(nodes, {"x", "y"})
        self.assertEqual(network["dictionary_digest"], dictionary.digest())

    def test_dictionary_cycle_is_rejected(self):
        dictionary = FixedDictionary()
        dictionary.add("a", "b")
        dictionary.add("b", "c")
        dictionary.add("c", "a")
        with self.assertRaises(MeshError) as caught:
            dictionary.resolve("a")
        self.assertEqual(caught.exception.code, "cycle")

    def test_multi_source_record_contributes_once(self):
        rows = [
            row("s1", "1", "w1", 2024, ["A", "B"]),
            row("s2", "1", "w1", 2024, ["A", "B"]),
            row("s3", "1", "w1", 2024, ["A", "B"]),
        ]
        network = NetworkBuilder(self.cfg(), FixedDictionary()).build(
            parse_work_table(rows)
        )
        weights = edge_map(network)
        self.assertEqual(weights, {("a", "b"): Fraction(1)})
        self.assertEqual(network["edges"][0]["work_count"], 1)
        self.assertEqual(
            sorted(network["edges"][0]["works"][0]["records"]),
            ["s1:1", "s2:1", "s3:1"],
        )

    def test_count_vs_fractional_weights_are_exact(self):
        # 一项 3 机构成果贡献 C(3,2)=3 个机构对。
        rows = [row("s", "1", "w1", 2024, ["A", "B", "C"])]
        counted = NetworkBuilder(self.cfg(weight_scheme="count"),
                                 FixedDictionary()).build(parse_work_table(rows))
        fractional = NetworkBuilder(
            self.cfg(weight_scheme="fractional"), FixedDictionary()
        ).build(parse_work_table(rows))
        self.assertTrue(
            all(weight == Fraction(1) for weight in edge_map(counted).values())
        )
        self.assertTrue(
            all(weight == Fraction(1, 3)
                for weight in edge_map(fractional).values())
        )
        # 单成果在 fractional 口径下总边权恒为 1。
        self.assertEqual(
            sum(edge_map(fractional).values(), Fraction(0)), Fraction(1)
        )
        # 精确表示：1/3 不被浮点舍入。
        self.assertEqual(
            fractional["edges"][0]["weight"]["exact"], "1/3"
        )
        self.assertEqual(
            fractional["edges"][0]["weight"]["denominator"], 3
        )

    def test_solo_work_is_node_contribution_without_edge(self):
        rows = [
            row("s", "1", "w1", 2024, ["A"]),
            row("s", "2", "w2", 2024, ["A", "B"]),
        ]
        network = NetworkBuilder(
            self.cfg(weight_scheme="fractional"), FixedDictionary()
        ).build(parse_work_table(rows))
        node_a = next(node for node in network["nodes"] if node["id"] == "a")
        self.assertEqual(Fraction(node_a["solo_weight"]["exact"]), Fraction(1))
        self.assertEqual(
            Fraction(node_a["collaboration_weight"]["exact"]), Fraction(1)
        )
        self.assertEqual(Fraction(node_a["strength"]["exact"]), Fraction(2))
        self.assertEqual(network["totals"]["edge_count"], 1)

    def test_missing_oversized_and_conflict_are_traceable_exclusions(self):
        rows = [
            row("s", "1", "empty", 2024, []),
            row("s", "2", "big", 2024, ["A", "B", "C"]),
            row("s", "3", "conflict", 2024, ["A", "B"]),
            row("t", "3", "conflict", 2024, ["A", "C"]),
        ]
        config = self.cfg(max_collaborators=2)
        network = NetworkBuilder(config, FixedDictionary()).build(
            parse_work_table(rows)
        )
        kinds = {item["kind"] for item in network["exclusions"]}
        self.assertEqual(
            kinds,
            {"missing_institution", "oversized_collaboration",
             "identity_conflict"},
        )
        self.assertEqual(network["totals"]["included_work_count"], 0)
        # 每条排除都能追回成果与来源记录。
        for item in network["exclusions"]:
            self.assertTrue(item["records"])

    def test_conflicting_year_is_identity_conflict(self):
        rows = [
            row("s", "1", "w1", 2024, ["A", "B"]),
            row("t", "1", "w1", 2025, ["A", "B"]),
        ]
        network = NetworkBuilder(self.cfg(), FixedDictionary()).build(
            parse_work_table(rows)
        )
        self.assertEqual(
            [item["reason"] for item in network["exclusions"]],
            ["conflicting_year"],
        )

    def test_year_window_filter_and_outside_window_log(self):
        rows = [
            row("s", "1", "old", 2019, ["A", "B"]),
            row("s", "2", "new", 2024, ["A", "C"]),
        ]
        network = NetworkBuilder(self.cfg(year_from=2020, year_to=2026),
                                 FixedDictionary()).build(parse_work_table(rows))
        self.assertEqual(
            [item["work_id"] for item in network["outside_window"]], ["old"]
        )
        self.assertEqual(network["totals"]["included_work_count"], 1)

    def test_source_coverage_filter_is_separate_exclusion(self):
        rows = [
            row("lab", "1", "w1", 2024, ["A", "B"]),
            row("extra", "2", "w2", 2024, ["C", "D"]),
        ]
        config = self.cfg(sources=["lab"])
        network = NetworkBuilder(config, FixedDictionary()).build(
            parse_work_table(rows)
        )
        self.assertEqual(
            [item["kind"] for item in network["exclusions"]],
            ["source_not_covered"],
        )
        self.assertEqual(network["totals"]["node_count"], 2)

    def test_invalid_rows_are_rejected(self):
        with self.assertRaises(MeshError):
            parse_work_table([{"record_key": "s:1", "work_id": "w",
                               "source": "s", "year": 2024,
                               "institutions": [1, 2]}])
        with self.assertRaises(MeshError):
            parse_work_table([{"record_key": "s:1", "work_id": "w",
                               "source": "other", "year": 2024,
                               "institutions": ["A"]}])

    def test_inactive_records_are_ignored(self):
        rows = [
            row("s", "1", "w1", 2024, ["A", "B"], active=False),
            row("s", "2", "w2", 2024, ["B", "C"]),
        ]
        network = NetworkBuilder(self.cfg(), FixedDictionary()).build(
            parse_work_table(rows)
        )
        self.assertEqual(edge_map(network), {("b", "c"): Fraction(1)})


if __name__ == "__main__":
    unittest.main()
