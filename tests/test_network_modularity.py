"""模块度、确定性 Louvain 与连通分量测试。"""

import itertools
import unittest
from fractions import Fraction

from researchmesh.contracts import MeshError
from researchmesh.network.modularity import (
    connected_components,
    louvain,
    louvain_restarts,
    modularity,
)


def bridge_graph():
    nodes = ["a", "b", "c", "d", "e", "f", "g"]
    edges = {
        ("a", "b"): Fraction(4),
        ("b", "c"): Fraction(4),
        ("c", "a"): Fraction(4),
        ("d", "e"): Fraction(4),
        ("e", "f"): Fraction(4),
        ("f", "d"): Fraction(4),
        ("c", "d"): Fraction(1),
    }
    return nodes, edges


def brute_force_best(nodes, edges, resolution=Fraction(1), colors=3):
    best = None
    for assignment in itertools.product(range(colors), repeat=len(nodes)):
        partition = dict(zip(nodes, assignment))
        score = modularity(partition, nodes, edges, resolution)
        if best is None or score > best[0]:
            best = (score, assignment)
    return best


class ModularityTests(unittest.TestCase):
    def test_components_differ_from_communities_on_bridge_graph(self):
        nodes, edges = bridge_graph()
        components = connected_components(nodes, edges)
        result = louvain(nodes, edges, resolution=Fraction(1), seed=7)
        # 连通性：g 孤立，其余 6 点经 c-d 桥连成一个分量。
        self.assertEqual(len(components), 2)
        self.assertEqual(max(components, key=len),
                         ["a", "b", "c", "d", "e", "f"])
        # 社区发现：主分量被模块度优化拆成两个社区，g 自成社区。
        labels = result["partition"]
        self.assertEqual(labels["a"], labels["b"])
        self.assertEqual(labels["a"], labels["c"])
        self.assertEqual(labels["d"], labels["e"])
        self.assertEqual(labels["d"], labels["f"])
        self.assertNotEqual(labels["c"], labels["d"])
        self.assertEqual(len(result["communities"]), 3)
        self.assertNotEqual(
            [sorted(group) for group in components],
            [entry["nodes"] for entry in result["communities"]],
        )
        self.assertGreater(Fraction(result["modularity"]["exact"]), 0)

    def test_louvain_reaches_brute_force_optimum(self):
        nodes, edges = bridge_graph()
        result = louvain(nodes, edges, resolution=Fraction(1), seed=7)
        optimum, _ = brute_force_best(nodes, edges)
        self.assertEqual(Fraction(result["modularity"]["exact"]), optimum)

    def test_edgeless_graph_has_deterministic_singletons(self):
        result = louvain(["x", "y", "z"], {}, seed=7)
        self.assertEqual(
            result["stop_reason"], "edgeless_graph_each_node_own_community"
        )
        self.assertEqual(result["modularity"]["exact"], "0")
        self.assertEqual(len(result["communities"]), 3)
        self.assertEqual(modularity({"x": 0, "y": 0}, ["x", "y"], {}), 0)

    def test_single_node_graph(self):
        result = louvain(["solo"], {}, seed=3)
        self.assertEqual(result["partition"], {"solo": "C1"})
        self.assertEqual(result["modularity"]["exact"], "0")

    def test_determinism_across_seeds_and_runs(self):
        nodes, edges = bridge_graph()
        first = louvain(nodes, edges, resolution=Fraction(1), seed=7)
        second = louvain(nodes, edges, resolution=Fraction(1), seed=7)
        self.assertEqual(first["partition"], second["partition"])
        self.assertEqual(first["modularity"], second["modularity"])
        # 节点顺序由种子决定并完整记录，可逐轮复核。
        self.assertEqual(
            first["level_history"][0]["node_order_seed"], 7
        )
        self.assertTrue(first["level_history"][0]["node_order"])

    def test_resolution_changes_partition_predictably(self):
        nodes, edges = bridge_graph()
        fine = louvain(nodes, edges, resolution=Fraction(2), seed=7)
        coarse = louvain(nodes, edges, resolution=Fraction(1, 2), seed=7)
        # 高分辨率鼓励更细的社区，低分辨率鼓励合并。
        self.assertGreaterEqual(
            len(fine["communities"]), len(coarse["communities"])
        )

    def test_invalid_resolution_rejected(self):
        with self.assertRaises(MeshError):
            louvain(["a", "b"], {("a", "b"): Fraction(1)},
                    resolution=Fraction(0))

    def test_stop_reason_is_reported(self):
        nodes, edges = bridge_graph()
        result = louvain(nodes, edges, seed=7)
        self.assertIn(
            result["stop_reason"],
            {"no_strictly_improving_move", "no_aggregation_possible",
             "modularity_gain_within_tolerance", "max_passes_reached",
             "max_levels_reached"},
        )
        for entry in result["level_history"]:
            self.assertIn("modularity_before", entry)
            self.assertIn("modularity_after", entry)

    def test_tolerance_can_stop_early(self):
        nodes, edges = bridge_graph()
        result = louvain(nodes, edges, tolerance=Fraction(1), seed=7)
        self.assertIn(result["stop_reason"],
                      {"modularity_gain_within_tolerance",
                       "no_strictly_improving_move"})

    def test_self_loop_and_weighted_strength(self):
        edges = {("a", "a"): Fraction(2), ("a", "b"): Fraction(3)}
        result = louvain(["a", "b"], edges, seed=1)
        self.assertIn(result["partition"]["a"], result["partition"].values())
        # 模块度可计算且为精确分数。
        self.assertIsInstance(
            Fraction(result["modularity"]["exact"]), Fraction
        )

    def test_community_labels_are_ordered_by_min_node(self):
        nodes, edges = bridge_graph()
        result = louvain(nodes, edges, seed=7)
        first_members = result["communities"][0]["nodes"]
        self.assertEqual(first_members[0], "a")
        self.assertEqual(
            [entry["community"] for entry in result["communities"]],
            ["C1", "C2", "C3"],
        )

    def test_restarts_are_deterministic_and_never_worse(self):
        import random

        rng = random.Random(42)
        nodes = ["n" + str(i) for i in range(30)]
        groups = [nodes[0:8], nodes[8:15], nodes[15:23], nodes[23:30]]
        edges = {}
        for group in groups:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    if rng.random() < 0.7:
                        edges[(group[i], group[j])] = Fraction(
                            rng.randint(1, 3)
                        )
        for _ in range(12):
            u, v = rng.choice(nodes), rng.choice(nodes)
            if u != v:
                key = tuple(sorted((u, v)))
                edges[key] = edges.get(key, Fraction(0)) + Fraction(1)

        first = louvain_restarts(nodes, edges, base_seed=7, restarts=40)
        second = louvain_restarts(nodes, edges, base_seed=7, restarts=40)
        # 完全确定：相同参数逐位复现。
        self.assertEqual(first["partition"], second["partition"])
        self.assertEqual(
            first["restart_selection"]["candidates"],
            second["restart_selection"]["candidates"],
        )
        # 重启最优不劣于任何单次起点。
        best_single = max(
            Fraction(louvain(nodes, edges, seed=s)["modularity"]["exact"])
            for s in range(7, 47)
        )
        self.assertEqual(
            Fraction(first["modularity"]["exact"]), best_single
        )
        # 候选与获胜种子都留痕，可复核选择过程。
        self.assertEqual(len(first["restart_selection"]["candidates"]), 40)
        self.assertIn("winning_seed", first["restart_selection"])
        # 至少不劣于植入的四团分区。
        planted = {n: idx for idx, group in enumerate(groups) for n in group}
        self.assertGreaterEqual(
            Fraction(first["modularity"]["exact"]),
            modularity(planted, nodes, edges),
        )

    def test_single_restart_equals_plain_louvain(self):
        nodes, edges = bridge_graph()
        plain = louvain(nodes, edges, seed=7)
        restarted = louvain_restarts(nodes, edges, base_seed=7, restarts=1)
        self.assertEqual(plain["partition"], restarted["partition"])
        self.assertEqual(plain["modularity"], restarted["modularity"])
        self.assertEqual(restarted["restart_selection"]["winning_seed"], 7)


if __name__ == "__main__":
    unittest.main()
