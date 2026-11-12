"""从发布成果表构建机构合作图。

口径保证：
* 机构别名经固定词典归一化，词典版本记入结果；
* 同一成果（work_id）的多来源记录合并为一个贡献单元，只贡献一次；
* 缺机构、超大联合成果、身份冲突进入可追溯排除项，不静默丢弃；
* 边权内部为 Fraction：count 整计，fractional 按 1/C(k,2) 分配；
* 单机构成果不产生边，但作为节点强度（solo 贡献）保留；
* 每条边附成果级来源台账，可逐条复核。
"""

from itertools import combinations
from collections import defaultdict
from fractions import Fraction

from ..contracts import fail, digest
from .rational import rational_payload
from .model import table_digest


class NetworkBuilder:
    def __init__(self, config, dictionary):
        self.config = config
        self.dictionary = dictionary

    def build(self, rows):
        cfg = self.config
        active_rows = [row for row in rows if row["active"]]

        # 年份窗在排除判定之外单独记录：时间窗进出不是数据质量问题。
        in_window = {}
        for row in active_rows:
            year = row["year"]
            in_window[row["record_key"]] = (
                year is not None and cfg.year_from <= year <= cfg.year_to
            )

        groups = defaultdict(list)
        for row in active_rows:
            groups[row["work_id"]].append(row)

        exclusions = []
        included_works = []
        outside_window = []
        for work_id in sorted(groups):
            members = sorted(groups[work_id], key=lambda row: row["record_key"])
            record_keys = [row["record_key"] for row in members]
            sources = sorted({row["source"] for row in members})

            # 来源覆盖过滤：固定共同来源口径下，不含任一允许来源的成果不参与。
            if cfg.sources is not None and not (set(cfg.sources) & set(sources)):
                exclusions.append(
                    {
                        "kind": "source_not_covered",
                        "work_id": work_id,
                        "records": record_keys,
                        "sources": sources,
                        "allowed_sources": list(cfg.sources),
                    }
                )
                continue

            years = {row["year"] for row in members if row["year"] is not None}
            if len(years) > 1:
                exclusions.append(
                    {
                        "kind": "identity_conflict",
                        "reason": "conflicting_year",
                        "work_id": work_id,
                        "records": record_keys,
                        "values": sorted(years),
                    }
                )
                continue

            normalized_sets = []
            for row in members:
                names = []
                for raw in row["institutions"]:
                    folded = raw.strip()
                    if folded:
                        names.append(self.dictionary.resolve(folded))
                normalized_sets.append(frozenset(names))
            if len(set(normalized_sets)) > 1:
                exclusions.append(
                    {
                        "kind": "identity_conflict",
                        "reason": "conflicting_institution_set",
                        "work_id": work_id,
                        "records": record_keys,
                        "values": [sorted(names) for names in normalized_sets],
                    }
                )
                continue

            window_members = [
                row
                for row in members
                if row["year"] is not None
                and cfg.year_from <= row["year"] <= cfg.year_to
            ]
            if not window_members:
                outside_window.append(
                    {
                        "work_id": work_id,
                        "records": record_keys,
                        "years": sorted(years),
                    }
                )
                continue

            institutions = sorted(normalized_sets[0])
            if not institutions:
                exclusions.append(
                    {
                        "kind": "missing_institution",
                        "work_id": work_id,
                        "records": record_keys,
                    }
                )
                continue
            if len(institutions) > cfg.max_collaborators:
                exclusions.append(
                    {
                        "kind": "oversized_collaboration",
                        "work_id": work_id,
                        "records": record_keys,
                        "institution_count": len(institutions),
                        "limit": cfg.max_collaborators,
                    }
                )
                continue

            year = next(iter(years)) if years else None
            included_works.append(
                {
                    "work_id": work_id,
                    "records": record_keys,
                    "sources": sources,
                    "year": year,
                    "institutions": institutions,
                    "k": len(institutions),
                }
            )

        edge_weights = defaultdict(Fraction)
        edge_provenance = defaultdict(list)
        solo_weights = defaultdict(Fraction)
        solo_provenance = defaultdict(list)
        node_order = set()
        work_edge_weight = {}

        for work in included_works:
            institutions = work["institutions"]
            k = work["k"]
            node_order.update(institutions)
            if k == 1:
                node = institutions[0]
                solo_weights[node] += Fraction(1)
                solo_provenance[node].append(
                    {"work_id": work["work_id"], "records": work["records"]}
                )
                work_edge_weight[work["work_id"]] = "0"
                continue
            pair_count = k * (k - 1) // 2
            per_edge = Fraction(1) if cfg.weight_scheme == "count" else Fraction(
                1, pair_count
            )
            work_edge_weight[work["work_id"]] = str(per_edge * pair_count)
            for left, right in combinations(sorted(institutions), 2):
                edge = (left, right)
                edge_weights[edge] += per_edge
                edge_provenance[edge].append(
                    {
                        "work_id": work["work_id"],
                        "records": work["records"],
                        "sources": work["sources"],
                        "k": k,
                        "pair_count": pair_count,
                        "edge_weight": str(per_edge),
                    }
                )

        nodes = []
        for node in sorted(node_order):
            strength = solo_weights[node]
            for (left, right), weight in edge_weights.items():
                if node in (left, right):
                    strength += weight
            nodes.append(
                {
                    "id": node,
                    "strength": rational_payload(strength),
                    "collaboration_weight": rational_payload(
                        strength - solo_weights[node]
                    ),
                    "solo_weight": rational_payload(solo_weights[node]),
                    "solo_works": len(solo_provenance[node]),
                    "degree": sum(1 for edge in edge_weights if node in edge),
                }
            )

        edges = []
        total_weight = Fraction(0)
        for edge in sorted(edge_weights):
            weight = edge_weights[edge]
            total_weight += weight
            edges.append(
                {
                    "source_node": edge[0],
                    "target_node": edge[1],
                    "weight": rational_payload(weight),
                    "work_count": len(edge_provenance[edge]),
                    "works": edge_provenance[edge],
                }
            )

        result = {
            "config": cfg.to_dict(),
            "config_digest": cfg.digest(),
            "dictionary": self.dictionary.to_dict(),
            "dictionary_digest": self.dictionary.digest(),
            "input_table_digest": table_digest(rows),
            "input_rows": len(rows),
            "active_rows": len(active_rows),
            "window": {"year_from": cfg.year_from, "year_to": cfg.year_to},
            "nodes": nodes,
            "edges": edges,
            "included_works": included_works,
            "exclusions": exclusions,
            "outside_window": outside_window,
            "unresolved_dictionary_names": self.dictionary.unresolved(),
            "totals": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "included_work_count": len(included_works),
                "excluded_work_count": len(exclusions),
                "total_edge_weight": rational_payload(total_weight),
                "total_solo_weight": rational_payload(sum(solo_weights.values(), Fraction(0))),
            },
        }
        result["network_digest"] = digest(
            {
                "config_digest": result["config_digest"],
                "dictionary_digest": result["dictionary_digest"],
                "input_table_digest": result["input_table_digest"],
                "nodes": [node["id"] for node in nodes],
                "edges": [
                    [edge["source_node"], edge["target_node"], edge["weight"]["exact"]]
                    for edge in edges
                ],
            }
        )
        # 结构摘要只依赖影响图结构的口径参数（年份窗、权重口径、来源过滤、
        # 分辨率、种子等）、词典与最终节点/边，不含发布名、描述或输入表摘要：
        # 两期原始表不同或发布名不同，也能判定网络结构是否一致。
        structural_config = {
            key: value
            for key, value in cfg.to_dict().items()
            if key not in {"release", "description", "tie_breaking",
                           "stop_rules"}
        }
        result["structure_digest"] = digest(
            {
                "structural_config": structural_config,
                "dictionary_digest": result["dictionary_digest"],
                "window": result["window"],
                "nodes": [
                    [node["id"], node["strength"]["exact"]] for node in nodes
                ],
                "edges": [
                    [edge["source_node"], edge["target_node"],
                     edge["weight"]["exact"]]
                    for edge in edges
                ],
            }
        )
        return result


def edge_map(network):
    """把网络结果转成 (u,v) -> Fraction 权重的便于计算的映射。"""
    result = {}
    for edge in network["edges"]:
        key = (edge["source_node"], edge["target_node"])
        if key in result:
            fail("integrity", "duplicate edge in network")
        result[key] = Fraction(edge["weight"]["exact"])
    return result


def node_strength_map(network):
    return {
        node["id"]: Fraction(node["strength"]["exact"]) for node in network["nodes"]
    }
