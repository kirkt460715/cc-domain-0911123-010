"""加权无向模块度与确定性 Louvain 社区发现。

全部模块度算术使用 Fraction，避免浮点累积误差影响严格增益判定。
确定性保证：
* 节点初始顺序为节点编号升序，之后每级用 random.Random(seed + level) 洗牌，
  同一组 (图, 分辨率, 种子) 结果逐位可复现；
* 每个节点按候选社区编号升序评估，仅当增益严格大于当前最优才替换，
  等增益平局保留最小编号社区；
* 增益不超过 tolerance（默认 0）的移动不执行。
社区是模块度优化的产物，与连通分量分别计算、分别输出，绝不混用。
"""

import random
from collections import defaultdict, deque
from fractions import Fraction

from ..contracts import integer, fail
from .rational import rational_payload


def _adjacency(nodes, edges):
    adjacency = {node: defaultdict(Fraction) for node in nodes}
    for (left, right), weight in edges.items():
        if left not in adjacency or right not in adjacency:
            fail("input", "edge references unknown node")
        adjacency[left][right] += weight
        adjacency[right][left] += weight
    return adjacency


def connected_components(nodes, edges):
    """按节点编号确定性遍历的连通分量。"""
    adjacency = {node: set() for node in nodes}
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    seen = set()
    components = []
    for start in sorted(nodes):
        if start in seen:
            continue
        queue = deque([start])
        seen.add(start)
        members = []
        while queue:
            current = queue.popleft()
            members.append(current)
            for peer in sorted(adjacency[current]):
                if peer not in seen:
                    seen.add(peer)
                    queue.append(peer)
        components.append(sorted(members))
    return sorted(components, key=lambda group: (group[0], len(group)))


def modularity(partition, nodes, edges, resolution=Fraction(1)):
    """Reichardt-Bornholdt / Newman 加权无向模块度（含自环与孤立点）。

    Q = 1/(2m) * sum_ij [ A_ij - gamma * k_i k_j / (2m) ] delta(c_i,c_j)
    无边图（2m=0）定义为 0。
    """
    if not isinstance(resolution, Fraction):
        resolution = Fraction(resolution)
    two_m = Fraction(2) * sum(edges.values(), Fraction(0))
    if two_m == 0:
        return Fraction(0)
    strength = {node: Fraction(0) for node in nodes}
    loops = {node: Fraction(0) for node in nodes}
    for (left, right), weight in edges.items():
        if left == right:
            loops[left] += weight
            strength[left] += 2 * weight
        else:
            strength[left] += weight
            strength[right] += weight
    inside = defaultdict(Fraction)
    community_strength = defaultdict(Fraction)
    for node, community in partition.items():
        community_strength[community] += strength[node]
    for (left, right), weight in edges.items():
        if partition[left] == partition[right]:
            inside[partition[left]] += 2 * weight
    score = Fraction(0)
    for community in set(partition.values()):
        score += (
            inside[community]
            - resolution * community_strength[community] ** 2 / two_m
        )
    return score / two_m


def _strengths(nodes, adjacency):
    result = {}
    for node in nodes:
        result[node] = sum(adjacency[node].values(), Fraction(0))
    return result


def _local_level(nodes, adjacency, strengths, partition, resolution, tolerance,
                 order, level_stats):
    """Louvain 局部移动阶段，返回 (新分区, 移动次数, 是否因上限停止)。"""
    two_m = Fraction(2) * sum(strengths.values(), Fraction(0))
    moves = 0
    capped = False
    if two_m == 0:
        return partition, 0, False
    community_of = dict(partition)
    community_total = defaultdict(Fraction)
    for node in nodes:
        community_total[community_of[node]] += strengths[node]

    improved_overall = True
    passes = 0
    while improved_overall:
        improved_overall = False
        passes += 1
        if passes > level_stats["max_passes"]:
            capped = True
            break
        for node in order:
            own_community = community_of[node]
            ki = strengths[node]
            # 节点连向各相邻社区（含自身所在社区）的总权重，自环计入自身社区。
            linked = defaultdict(Fraction)
            for peer, weight in adjacency[node].items():
                if peer == node:
                    linked[own_community] += weight
                else:
                    linked[community_of[peer]] += weight

            # 直接比较模块度社区分量的变化：
            # 留在原社区为基准（增益 0）；移入 candidate 时，原社区与目标
            # 社区的强度都按“节点离开/加入后”取值，公式对任何分区均严格成立。
            # deltaQ = (k_i_in - k_i_self)/2m
            #        - gamma*k_i*(sigma_tot_candidate - sigma_tot_own + k_i)/(2m)
            best_community = own_community
            best_gain = Fraction(0)
            for candidate in sorted(linked):
                if candidate == own_community:
                    continue
                gain = (
                    linked[candidate] - linked[own_community]
                    - resolution
                    * ki
                    * (
                        community_total[candidate]
                        - community_total[own_community]
                        + ki
                    )
                    / two_m
                )
                # 候选按社区编号升序评估，仅严格更优才替换：
                # 等增益平局保留编号最小的候选；非正增益永不移动，
                # 因此局部阶段在有限图上必然终止（无循环游走）。
                if gain > best_gain:
                    best_gain = gain
                    best_community = candidate
            if best_community != own_community and best_gain > tolerance:
                community_total[own_community] -= ki
                community_total[best_community] += ki
                community_of[node] = best_community
                moves += 1
                improved_overall = True
    level_stats["passes_used"] = passes
    return community_of, moves, capped


def louvain(nodes, edges, *, resolution=Fraction(1), seed=7, tolerance=Fraction(0),
            max_passes=100, max_levels=50):
    """确定性多级 Louvain，返回可复核的完整结果。"""
    integer(seed, 0, 2**32 - 1)
    integer(max_passes, 1, 10000)
    integer(max_levels, 1, 1000)
    if not isinstance(resolution, Fraction):
        resolution = Fraction(resolution)
    if not isinstance(tolerance, Fraction):
        tolerance = Fraction(tolerance)
    if resolution <= 0:
        fail("input", "resolution must be positive")
    nodes = sorted(nodes)
    adjacency = _adjacency(nodes, edges)
    strengths = _strengths(nodes, adjacency)

    # 当前层级的元节点：每个元节点 -> 原始节点集合
    members = {node: (node,) for node in nodes}
    # 原始节点 -> 当前社区（元节点）
    partition = {node: node for node in nodes}
    level = 0
    history = []
    stop_reason = None
    capped = False

    if not edges or sum(edges.values(), Fraction(0)) == 0:
        stop_reason = "edgeless_graph_each_node_own_community"
    initial_q = modularity(partition, nodes, edges, resolution)

    while stop_reason is None:
        level += 1
        if level > max_levels:
            stop_reason = "max_levels_reached"
            capped = True
            break
        # 依据当前元节点成员，把原始边显式聚合成本层元图边（含自环）。
        original_to_meta = {}
        for meta, originals in members.items():
            for original in originals:
                original_to_meta[original] = meta
        meta_edges = defaultdict(Fraction)
        for (left, right), weight in edges.items():
            a, b = original_to_meta[left], original_to_meta[right]
            key = tuple(sorted((a, b)))
            meta_edges[key] += weight
        meta_nodes = sorted(members)
        meta_adjacency = _adjacency(meta_nodes, dict(meta_edges))
        meta_strengths = _strengths(meta_nodes, meta_adjacency)
        meta_partition = {node: node for node in meta_nodes}
        rng = random.Random(seed + level - 1)
        order = list(meta_nodes)
        rng.shuffle(order)
        stats = {"max_passes": max_passes, "passes_used": 0}
        meta_partition, moves, level_capped = _local_level(
            meta_nodes,
            meta_adjacency,
            meta_strengths,
            meta_partition,
            resolution,
            tolerance,
            order,
            stats,
        )
        capped = capped or level_capped
        q_before = modularity(
            {node: partition[node] for node in nodes},
            nodes,
            edges,
            resolution,
        )
        # 把元节点分区映射回原始节点。
        new_partition = {
            original: meta_partition[meta]
            for meta, originals in members.items()
            for original in originals
        }
        q_after = modularity(new_partition, nodes, edges, resolution)
        history.append(
            {
                "level": level,
                "meta_nodes": len(meta_nodes),
                "moves": moves,
                "passes_used": stats["passes_used"],
                "node_order_seed": seed + level - 1,
                "node_order": list(order),
                "modularity_before": rational_payload(q_before),
                "modularity_after": rational_payload(q_after),
            }
        )
        partition = new_partition
        if level_capped:
            stop_reason = "max_passes_reached"
            break
        if moves == 0:
            stop_reason = "no_strictly_improving_move"
            break
        # 聚合：把同社区元节点合并成下一层的新元节点。
        grouped = defaultdict(list)
        for meta in meta_nodes:
            grouped[meta_partition[meta]].append(meta)
        next_members = {}
        for community_id, group in grouped.items():
            merged = tuple(
                sorted(
                    original
                    for meta in group
                    for original in members[meta]
                )
            )
            next_members[merged] = merged
        if len(next_members) == len(members):
            stop_reason = "no_aggregation_possible"
            break
        members = next_members
        if q_after - q_before <= tolerance:
            stop_reason = "modularity_gain_within_tolerance"
            break

    # 社区编号按最小原始节点名确定，输出不依赖内部元节点 id。
    labels = {}
    for community in sorted(set(partition.values()), key=lambda c: min(
        node for node in partition if partition[node] == c
    )):
        labels[community] = "C" + str(len(labels) + 1)
    communities = defaultdict(list)
    for node in nodes:
        communities[labels[partition[node]]].append(node)
    final = {label: sorted(member_nodes) for label, member_nodes in communities.items()}
    final_q = modularity(
        {node: label for label, member_nodes in final.items() for node in member_nodes},
        nodes,
        edges,
        resolution,
    )
    # 独立复核：用输出分区重算模块度，并与历史末值比对。
    independent_q = modularity(
        {node: partition[node] for node in nodes}, nodes, edges, resolution
    )
    if independent_q != final_q:
        fail("integrity", "modularity cross-check failed")
    return {
        "algorithm": "deterministic-louvain-v1",
        "resolution": str(resolution),
        "seed": seed,
        "tolerance": str(tolerance),
        "max_passes": max_passes,
        "max_levels": max_levels,
        "tie_breaking": (
            "候选按社区编号升序评估，仅严格增益替换；"
            "等增益保留最小编号社区；节点顺序由 Random(seed+level) 确定。"
        ),
        "stop_reason": stop_reason,
        "levels_used": len(history),
        "level_history": history,
        "modularity": rational_payload(final_q),
        "initial_modularity": rational_payload(initial_q),
        "communities": [
            {
                "community": label,
                "nodes": member_nodes,
                "size": len(member_nodes),
                "internal_weight": rational_payload(
                    _internal_weight(member_nodes, edges)
                ),
            }
            for label, member_nodes in sorted(final.items())
        ],
        "partition": {node: labels[partition[node]] for node in nodes},
        "capped": capped,
    }


def _internal_weight(member_nodes, edges):
    members = set(member_nodes)
    total = Fraction(0)
    for (left, right), weight in edges.items():
        if left in members and right in members:
            total += weight
    return total


def louvain_restarts(nodes, edges, *, base_seed=7, restarts=10,
                     resolution=Fraction(1), tolerance=Fraction(0),
                     max_passes=100, max_levels=50):
    """确定性多起点重启：对 base_seed..base_seed+restarts-1 各跑一次。

    选择规则完全确定：先按模块度严格最大，平局再按社区数更少、
    获胜种子编号更小排序。所有候选的模块度与种子都保留在结果里，
    可复核为何选中该分区。Louvain 是启发式算法，重启可降低陷入
    较差局部最优的概率，但不保证全局最优。
    """
    integer(restarts, 1, 1000)
    candidates = []
    for offset in range(restarts):
        seed = base_seed + offset
        result = louvain(
            nodes, edges, resolution=resolution, seed=seed,
            tolerance=tolerance, max_passes=max_passes,
            max_levels=max_levels,
        )
        candidates.append(
            {
                "seed": seed,
                "modularity": result["modularity"]["exact"],
                "community_count": len(result["communities"]),
                "stop_reason": result["stop_reason"],
            }
        )
    winner = louvain(
        nodes, edges, resolution=resolution, seed=base_seed,
        tolerance=tolerance, max_passes=max_passes,
        max_levels=max_levels,
    )
    winning_seed = base_seed
    best_q = Fraction(winner["modularity"]["exact"])
    for entry in candidates[1:]:
        candidate_q = Fraction(entry["modularity"])
        if (candidate_q, -entry["community_count"], -entry["seed"]) > (
            best_q, -len(winner["communities"]), -winning_seed
        ):
            rerun = louvain(
                nodes, edges, resolution=resolution, seed=entry["seed"],
                tolerance=tolerance, max_passes=max_passes,
                max_levels=max_levels,
            )
            winner, winning_seed, best_q = rerun, entry["seed"], candidate_q
    winner["restart_selection"] = {
        "method": "deterministic-louvain-restarts-v1",
        "base_seed": base_seed,
        "restarts": restarts,
        "selection_rule": "max modularity, then fewer communities, "
                          "then smaller seed on ties",
        "winning_seed": winning_seed,
        "candidates": candidates,
    }
    return winner


def analyze(network, config):
    """对建图结果计算分量与社区，合并成一份网络分析结果。"""
    from .builder import edge_map

    nodes = [node["id"] for node in network["nodes"]]
    edges = edge_map(network)
    components = connected_components(nodes, edges)
    kwargs = dict(
        resolution=config.resolution,
        tolerance=config.tolerance,
        max_passes=config.max_passes,
        max_levels=config.max_levels,
    )
    if getattr(config, "restarts", 1) > 1:
        community_result = louvain_restarts(
            nodes, edges, base_seed=config.seed,
            restarts=config.restarts, **kwargs
        )
    else:
        community_result = louvain(nodes, edges, seed=config.seed, **kwargs)
    component_payload = [
        {
            "component": "K" + str(index + 1),
            "nodes": members,
            "size": len(members),
            "isolated": len(members) == 1 and members[0] not in {
                node for edge in edges for node in edge
            },
        }
        for index, members in enumerate(components)
    ]
    # 明确区分：社区数与连通分量数可能不同（桥边图的核心教学点）。
    return {
        **network,
        "components": component_payload,
        "communities_result": community_result,
        "component_count": len(components),
        "community_count": len(community_result["communities"]),
        "components_equal_communities": [
            sorted(group) for group in components
        ]
        == [
            entry["nodes"]
            for entry in sorted(
                community_result["communities"], key=lambda item: item["nodes"][0]
            )
        ],
    }
