"""跨时期社区的全局一对一匹配。

匹配基于共同节点的加权重叠，用带确定性平局规则的匈牙利（Kuhn-Munkres）
算法求全局最优，而不是逐个贪心配对或依赖社区编号。
"""

from fractions import Fraction
from .rational import rational_payload


def _hungarian(cost):
    """方阵最小指派，cost 为 Fraction 二维列表；返回行 -> 列。

    平局规则：只在严格更小时更新标记，因此等成本指派保留最小列编号，
    结果只依赖矩阵内容，与迭代顺序无关。
    """
    n = len(cost)
    if n == 0:
        return {}
    u = [Fraction(0)] * (n + 1)
    v = [Fraction(0)] * (n + 1)
    way = [0] * (n + 1)
    potential = [Fraction(0)] * (n + 1)
    for i in range(1, n + 1):
        potential[0] = i
        minv = [None] * (n + 1)
        used = [False] * (n + 1)
        column = 0
        while True:
            used[column] = True
            row = potential[column]
            delta = None
            column1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                current = cost[row - 1][j - 1] - u[row] - v[j]
                if minv[j] is None or current < minv[j]:
                    minv[j] = current
                    way[j] = column
                if delta is None or minv[j] < delta:
                    delta = minv[j]
                    column1 = j
            for j in range(n + 1):
                if used[j]:
                    u[potential[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            column = column1
            if potential[column] == 0:
                break
        while True:
            column1 = way[column]
            potential[column] = potential[column1]
            column = column1
            if column == 0:
                break
    assignment = {}
    for column in range(1, n + 1):
        assignment[potential[column] - 1] = column - 1
    return assignment


def _node_weight_map(analysis):
    # 节点权重 = 总强度（合作边权 + 单机构成果贡献），用于加权重叠。
    return {
        node["id"]: Fraction(node["strength"]["exact"])
        for node in analysis["nodes"]
    }


def _community_nodes(analysis):
    return {
        entry["community"]: set(entry["nodes"])
        for entry in analysis["communities_result"]["communities"]
    }


def match_communities(before, after, *, overlap_threshold=Fraction(0)):
    """全局一对一匹配两个时期（建议传入共同来源覆盖下的网络）。"""
    if not isinstance(overlap_threshold, Fraction):
        overlap_threshold = Fraction(overlap_threshold)
    left_nodes = _community_nodes(before)
    right_nodes = _community_nodes(after)
    left_weight = _node_weight_map(before)
    right_weight = _node_weight_map(after)
    left_labels = sorted(left_nodes)
    right_labels = sorted(right_nodes)
    if not left_labels or not right_labels:
        # 某期在该口径下没有节点（例如全部落在年份窗外）：
        # 返回结构完整的空匹配，由调用方结合覆盖报告解读，而不是崩溃。
        return {
            "method": "hungarian_global_one_to_one_v1",
            "overlap_definition": (
                "对共同节点取两期节点强度的对称平均求和；"
                "匈牙利算法最大化总加权重叠，零权填充保持方阵。"
            ),
            "tie_breaking": "等成本保留最小社区编号；绝不按编号或贪心顺序配对。",
            "overlap_threshold": str(overlap_threshold),
            "overlap_matrix": [],
            "matches": [],
            "unmatched_before": left_labels,
            "unmatched_after": right_labels,
            "splits": [],
            "merges": [],
            "note": "one period has no nodes under this coverage; "
                    "no pairing is possible",
        }

    overlap = {}
    for left in left_labels:
        for right in right_labels:
            shared = left_nodes[left] & right_nodes[right]
            if not shared:
                overlap[(left, right)] = Fraction(0)
                continue
            # 两侧节点权重的对称平均：避免某期整体强度放大主导匹配。
            overlap[(left, right)] = sum(
                (left_weight.get(node, Fraction(0)) +
                 right_weight.get(node, Fraction(0))) / 2
                for node in shared
            )

    size = max(len(left_labels), len(right_labels))
    cost = [[Fraction(0) for _ in range(size)] for _ in range(size)]
    for i, left in enumerate(left_labels):
        for j, right in enumerate(right_labels):
            cost[i][j] = -overlap[(left, right)]
    assignment = _hungarian(cost)

    matches = []
    matched_left, matched_right = set(), set()
    for i, j in sorted(assignment.items()):
        if i >= len(left_labels) or j >= len(right_labels):
            continue
        left, right = left_labels[i], right_labels[j]
        weight = overlap[(left, right)]
        if weight <= overlap_threshold:
            continue
        shared = sorted(left_nodes[left] & right_nodes[right])
        matches.append(
            {
                "before_community": left,
                "after_community": right,
                "overlap_weight": rational_payload(weight),
                "shared_nodes": shared,
                "shared_node_count": len(shared),
                "before_only_nodes": sorted(left_nodes[left] - right_nodes[right]),
                "after_only_nodes": sorted(right_nodes[right] - left_nodes[left]),
            }
        )
        matched_left.add(left)
        matched_right.add(right)

    matrix = [
        {
            "before_community": left,
            "after_community": right,
            "overlap_weight": rational_payload(overlap[(left, right)]),
            "shared_nodes": sorted(left_nodes[left] & right_nodes[right]),
        }
        for left in left_labels
        for right in right_labels
    ]
    return {
        "method": "hungarian_global_one_to_one_v1",
        "overlap_definition": (
            "对共同节点取两期节点强度的对称平均求和；"
            "匈牙利算法最大化总加权重叠，零权填充保持方阵。"
        ),
        "tie_breaking": "等成本保留最小社区编号；绝不按编号或贪心顺序配对。",
        "overlap_threshold": str(overlap_threshold),
        "overlap_matrix": matrix,
        "matches": sorted(
            matches, key=lambda item: (-Fraction(item["overlap_weight"]["exact"]),
                                       item["before_community"],
                                       item["after_community"])
        ),
        "unmatched_before": sorted(set(left_labels) - matched_left),
        "unmatched_after": sorted(set(right_labels) - matched_right),
        "splits": _splits(left_labels, right_labels, overlap, matched_left,
                          matched_right),
        "merges": _merges(left_labels, right_labels, overlap, matched_left,
                          matched_right),
    }


def _splits(left_labels, right_labels, overlap, matched_left, matched_right):
    result = []
    for left in left_labels:
        if left in matched_left:
            continue
        targets = sorted(
            right
            for right in right_labels
            if right not in matched_right and overlap[(left, right)] > 0
        )
        if len(targets) > 1:
            result.append({"before_community": left, "into_after": targets})
    return result


def _merges(left_labels, right_labels, overlap, matched_left, matched_right):
    result = []
    for right in right_labels:
        if right in matched_right:
            continue
        origins = sorted(
            left
            for left in left_labels
            if left not in matched_left and overlap[(left, right)] > 0
        )
        if len(origins) > 1:
            result.append({"after_community": right, "from_before": origins})
    return result
