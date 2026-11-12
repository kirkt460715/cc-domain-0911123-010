"""全局一对一社区匹配与两期比较测试。"""

import unittest
from fractions import Fraction

from researchmesh.network import (
    FixedDictionary,
    NetworkConfig,
    NetworkBuilder,
)
from researchmesh.network.modularity import analyze
from researchmesh.network.matching import match_communities, _hungarian
from researchmesh.network.compare import compare_periods


def row(source, local, work, year, inst, active=True):
    return {
        "record_key": source + ":" + local,
        "work_id": work,
        "source": source,
        "year": year,
        "institutions": inst,
        "active": active,
    }


def build(rows, sources=None, dictionary=None, seed=7):
    config = NetworkConfig(
        release="r", year_from=2020, year_to=2026,
        weight_scheme="fractional", seed=seed, sources=sources,
    )
    return analyze(
        NetworkBuilder(config, dictionary or FixedDictionary()).build(rows),
        config,
    )


class HungarianTests(unittest.TestCase):
    def test_identity_assignment_on_zero_cost(self):
        cost = [[Fraction(0)] * 3 for _ in range(3)]
        self.assertEqual(_hungarian(cost), {0: 0, 1: 1, 2: 2})

    def test_global_optimum_beats_greedy(self):
        # 贪心按行选最小会选 (0,0)=1,(1,1)=100 共 101；
        # 全局最优是 (0,1)=2,(1,0)=2 共 4。
        cost = [
            [Fraction(1), Fraction(2)],
            [Fraction(2), Fraction(100)],
        ]
        assignment = _hungarian(cost)
        self.assertEqual(assignment, {0: 1, 1: 0})

    def test_rectangular_padding(self):
        cost = [
            [Fraction(0), Fraction(-5), Fraction(0)],
            [Fraction(0), Fraction(0), Fraction(-9)],
            [Fraction(0), Fraction(0), Fraction(0)],
        ]
        assignment = _hungarian(cost)
        self.assertEqual(len(assignment), 3)
        self.assertEqual(len(set(assignment.values())), 3)


class MatchingTests(unittest.TestCase):
    def test_one_to_one_matching_by_weighted_overlap(self):
        before = build([
            row("s", "1", "w1", 2024, ["A", "B"]),
            row("s", "2", "w2", 2024, ["B", "C"]),
            row("s", "3", "w3", 2024, ["X", "Y"]),
        ])
        after = build([
            row("s", "1", "w1", 2024, ["A", "B"]),
            row("s", "2", "w2", 2024, ["B", "C"]),
            row("s", "3", "w3", 2024, ["X", "Y"]),
        ])
        result = match_communities(before, after)
        self.assertEqual(result["method"], "hungarian_global_one_to_one_v1")
        # 每个社区至多匹配一次。
        lefts = [m["before_community"] for m in result["matches"]]
        rights = [m["after_community"] for m in result["matches"]]
        self.assertEqual(len(lefts), len(set(lefts)))
        self.assertEqual(len(rights), len(set(rights)))
        self.assertFalse(result["splits"] and result["merges"] is not None)

    def test_split_is_reported_not_greedily_paired(self):
        before = build([
            row("s", "1", "w1", 2024, ["A", "B"]),
            row("s", "2", "w2", 2024, ["B", "C"]),
            row("s", "3", "w3", 2024, ["C", "A"]),
        ])
        # 后期：原团体拆成两个弱连接部分，加一个新独立团体。
        after = build([
            row("s", "1", "w1", 2024, ["A", "B"]),
            row("s", "4", "w4", 2024, ["C", "Z"]),
        ])
        result = match_communities(before, after)
        self.assertTrue(result["overlap_matrix"])
        # 未匹配与重叠矩阵同时保留，可人工复核，而不是静默配对。
        self.assertTrue(
            result["unmatched_before"] or result["unmatched_after"]
            or result["splits"] or result["merges"]
        )


class ComparisonTests(unittest.TestCase):
    def _configs(self):
        # 两期使用相同年份窗，差异只来自发布内容与来源覆盖。
        return (
            NetworkConfig(release="r1", year_from=2020, year_to=2026,
                          weight_scheme="fractional", seed=7),
            NetworkConfig(release="r2", year_from=2020, year_to=2026,
                          weight_scheme="fractional", seed=7),
        )

    def test_new_source_changes_full_but_not_common_network(self):
        before = [
            row("lab", "1", "w1", 2025, ["A", "B"]),
            row("lab", "2", "w2", 2025, ["B", "C"]),
        ]
        after = [
            row("lab", "1", "w1", 2025, ["A", "B"]),
            row("lab", "2", "w2", 2025, ["B", "C"]),
            # 新来源的重复副本：不增加边权。
            row("extra", "1", "w1", 2025, ["A", "B"]),
            # 新来源独有成果：只影响全量网络。
            row("extra", "9", "w9", 2026, ["C", "H"]),
        ]
        c1, c2 = self._configs()
        result = compare_periods(
            before, after, c1, c2,
            FixedDictionary(), FixedDictionary(),
        )
        self.assertEqual(result["common_sources"], ["lab"])
        before_common = result["periods"]["before"]["common_coverage"]
        after_common = result["periods"]["after"]["common_coverage"]
        after_full = result["periods"]["after"]["full"]
        # 共同来源口径：两期网络结构完全一致（新来源被剥离）。
        self.assertEqual(
            before_common["structure_digest"],
            after_common["structure_digest"],
        )
        # 全量口径：新来源带来新节点 H 和新边。
        self.assertGreater(
            after_full["totals"]["edge_count"],
            after_common["totals"]["edge_count"],
        )
        # 重复副本没有让 w1 贡献两次。
        common_edge = next(
            edge for edge in after_common["edges"]
            if edge["source_node"] == "a"
        )
        full_edge = next(
            edge for edge in after_full["edges"]
            if edge["source_node"] == "a"
        )
        self.assertEqual(common_edge["work_count"], full_edge["work_count"])

    def test_no_common_source_is_rejected(self):
        c1, c2 = self._configs()
        with self.assertRaises(Exception):
            compare_periods(
                [row("lab", "1", "w1", 2025, ["A"])],
                [row("other", "1", "w1", 2025, ["A"])],
                c1, c2, FixedDictionary(), FixedDictionary(),
            )

    def test_edge_attribution_covers_all_change_types(self):
        before = [
            row("lab", "1", "kept", 2025, ["A", "B"]),
            row("lab", "2", "gone", 2025, ["B", "C"]),
            row("lab", "3", "dictw", 2025, ["A2", "B"]),
        ]
        after = [
            row("lab", "1", "kept", 2025, ["A", "B"]),
            row("lab", "2", "gone", 2025, ["B", "C"], active=False),
            row("lab", "3", "dictw", 2025, ["A2", "B"]),
            row("lab", "4", "fresh", 2026, ["B", "E"]),
        ]
        c1, c2 = self._configs()
        result = compare_periods(
            before, after, c1, c2,
            FixedDictionary(),
            FixedDictionary({"a2": "a"}),
            attribution={
                "gone": {"category": "work_withdrawn", "reason": "snapshot"},
                "fresh": {"category": "work_added", "reason": "new project"},
                "dictw": {"category": "institution_revision",
                          "reason": "dictionary revision"},
            },
        )
        categories = {
            cause["category"]
            for edge in result["edge_differences"]["changed_edges"]
            for cause in edge["attribution"]
        }
        self.assertIn("work_withdrawn", categories)
        self.assertIn("work_added", categories)
        self.assertIn("institution_revision", categories)
        for edge in result["edge_differences"]["changed_edges"]:
            self.assertTrue(edge["interpretation"])
            # 每条变化都能追到具体成果。
            for cause in edge["attribution"]:
                if "work_id" in cause:
                    self.assertTrue(cause["work_id"])

    def test_window_transition_is_not_called_performance(self):
        before = [row("lab", "1", "future", 2026, ["A", "E"])]
        after = [row("lab", "1", "future", 2026, ["A", "E"])]
        c1 = NetworkConfig(release="r1", year_from=2024, year_to=2025,
                           weight_scheme="fractional", seed=7)
        c2 = NetworkConfig(release="r2", year_from=2025, year_to=2026,
                           weight_scheme="fractional", seed=7)
        result = compare_periods(
            before, after, c1, c2,
            FixedDictionary(), FixedDictionary(),
        )
        changed = result["edge_differences"]["changed_edges"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(
            changed[0]["attribution"][0]["category"], "window_transition"
        )
        self.assertIn("不得计为组织合作绩效", changed[0]["interpretation"])
        # 前期该口径无节点时，匹配返回结构完整的空结果。
        self.assertIn(
            "note", result["community_matching"]
        )


if __name__ == "__main__":
    unittest.main()
