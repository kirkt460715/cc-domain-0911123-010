"""两个时期的合作网络比较。

对每个时期同时输出：
* 全量网络（该发布版可见的全部来源）；
* 固定共同来源覆盖网络（两期来源集合的交集），用于剥离新来源接入的影响。

边变化按成果级证据归因，区分真实合作变化与来源覆盖变化，
绝不把口径（来源、词典、身份）变化解释为组织绩效。
"""

from fractions import Fraction
from itertools import combinations

from ..contracts import digest, fail
from .config import NetworkConfig
from .builder import NetworkBuilder, edge_map
from .modularity import analyze
from .matching import match_communities
from .model import parse_work_table
from .rational import rational_payload


def _work_snapshots(rows):
    """work_id -> 该期融合后的成果视图（机构集合、年份、来源、记录键）。"""
    grouped = {}
    for row in rows:
        if not row["active"]:
            continue
        entry = grouped.setdefault(
            row["work_id"],
            {"institution_sets": [], "years": set(), "sources": set(),
             "records": []},
        )
        entry["institution_sets"].append(frozenset(row["institutions"]))
        if row["year"] is not None:
            entry["years"].add(row["year"])
        entry["sources"].add(row["source"])
        entry["records"].append(row["record_key"])
    return grouped


def _edge_contributions(works, dictionary):
    """返回 边 -> {work_id: Fraction}，机构名按当期词典归一化。"""
    contributions = {}
    for work_id, entry in works.items():
        names = set()
        for raw_set in entry["institution_sets"]:
            for name in raw_set:
                if name and name.strip():
                    names.add(dictionary.resolve(name))
        names = sorted(names)
        k = len(names)
        if k < 2:
            continue
        per_edge = Fraction(1, k * (k - 1) // 2)
        for edge in combinations(names, 2):
            contributions.setdefault(edge, {})[work_id] = per_edge
    return contributions


def compare_periods(before_table, after_table, before_config, after_config,
                    before_dictionary, after_dictionary,
                    *, weight_scheme=None, attribution=None):
    """构建两期全量/共同来源网络并做边、社区两层比较。"""
    if weight_scheme is not None:
        before_config = _with_scheme(before_config, weight_scheme)
        after_config = _with_scheme(after_config, weight_scheme)
    before_table = parse_work_table(before_table)
    after_table = parse_work_table(after_table)
    common_sources = sorted(
        set(_sources_of(before_table)) & set(_sources_of(after_table))
    )
    if not common_sources:
        fail("input", "periods share no common source coverage")

    def build(table, config, dictionary, sources):
        if sources is None:
            cfg = config
        else:
            cfg = NetworkConfig(
                # 共同来源口径的发布标签统一，避免发布名本身进入摘要差异；
                # 原始发布仍完整记录在全量网络与分析包中。
                release="common-coverage",
                year_from=config.year_from,
                year_to=config.year_to,
                weight_scheme=config.weight_scheme,
                max_collaborators=config.max_collaborators,
                resolution=config.resolution,
                seed=config.seed,
                tolerance=config.tolerance,
                max_passes=config.max_passes,
                max_levels=config.max_levels,
                restarts=config.restarts,
                sources=sources,
                dictionary_revision=config.dictionary_revision,
                description=(
                    (config.description + " " if config.description else "")
                    + "固定共同来源覆盖: " + ",".join(sources)
                ),
            )
        return analyze(NetworkBuilder(cfg, dictionary).build(table), cfg)

    before_full = build(before_table, before_config, before_dictionary, None)
    after_full = build(after_table, after_config, after_dictionary, None)
    before_common = build(before_table, before_config, before_dictionary,
                          common_sources)
    after_common = build(after_table, after_config, after_dictionary,
                         common_sources)

    matching = match_communities(before_common, after_common)
    before_present = {
        row["work_id"] for row in before_table if row["active"]
    }
    after_present = {
        row["work_id"] for row in after_table if row["active"]
    }
    edge_diff = _edge_differences(
        before_table, after_table,
        before_common, after_common,
        before_dictionary, after_dictionary,
        attribution or {},
        before_present, after_present,
    )
    result = {
        "common_sources": common_sources,
        "periods": {
            "before": {"full": before_full, "common_coverage": before_common},
            "after": {"full": after_full, "common_coverage": after_common},
        },
        "community_matching": matching,
        "edge_differences": edge_diff,
        "coverage_warning": _coverage_warning(
            before_full, after_full, before_common, after_common
        ),
    }
    result["comparison_digest"] = digest(
        {
            "before_full": before_full["network_digest"],
            "after_full": after_full["network_digest"],
            "before_common": before_common["network_digest"],
            "after_common": after_common["network_digest"],
            "common_sources": common_sources,
        }
    )
    return result


def _with_scheme(config, scheme):
    return NetworkConfig(
        release=config.release,
        year_from=config.year_from,
        year_to=config.year_to,
        weight_scheme=scheme,
        max_collaborators=config.max_collaborators,
        resolution=config.resolution,
        seed=config.seed,
        tolerance=config.tolerance,
        max_passes=config.max_passes,
        max_levels=config.max_levels,
        restarts=config.restarts,
        sources=config.sources,
        dictionary_revision=config.dictionary_revision,
        description=config.description,
    )


def _sources_of(table):
    return sorted({row["source"] for row in table if row["active"]})


def _edge_differences(before_table, after_table, before_net, after_net,
                      before_dict, after_dict, attribution,
                      before_present, after_present):
    before_works = _work_snapshots(before_table)
    after_works = _work_snapshots(after_table)
    # before_present/after_present 由调用方基于全部 active 行给出（含被年份窗、
    # 来源覆盖或排除规则挡在网络之外的成果），用来区分“时间窗进出”与
    # “新增/撤回”；works 快照只含实际进入网络的成果。
    # 归因只看实际进入该期网络（通过年份窗、来源覆盖与排除规则）的成果，
    # 因此时间窗进出的成果会表现为贡献集合的差，而不是静默留在两侧。
    before_included = {work["work_id"] for work in before_net["included_works"]}
    after_included = {work["work_id"] for work in after_net["included_works"]}
    before_contrib = _edge_contributions(
        {work_id: entry for work_id, entry in before_works.items()
         if work_id in before_included}, before_dict)
    after_contrib = _edge_contributions(
        {work_id: entry for work_id, entry in after_works.items()
         if work_id in after_included}, after_dict)
    before_edges = edge_map(before_net)
    after_edges = edge_map(after_net)
    all_edges = sorted(set(before_edges) | set(after_edges))
    rows = []
    for edge in all_edges:
        old_weight = before_edges.get(edge, Fraction(0))
        new_weight = after_edges.get(edge, Fraction(0))
        if old_weight == new_weight:
            continue
        causes = _attribute_edge(
            edge, before_works, after_works,
            before_contrib, after_contrib,
            before_dict, after_dict, attribution,
            before_present, after_present,
        )
        rows.append(
            {
                "edge": {"source_node": edge[0], "target_node": edge[1]},
                "before_weight": rational_payload(old_weight),
                "after_weight": rational_payload(new_weight),
                "delta": rational_payload(new_weight - old_weight),
                "kind": "added" if old_weight == 0 else (
                    "removed" if new_weight == 0 else "weight_changed"
                ),
                "attribution": causes,
                "interpretation": (
                    "来源覆盖或身份/词典口径变化，不得计为组织合作绩效"
                    if any(cause["category"] in {
                        "source_coverage", "identity_merge",
                        "identity_split", "identity_change_review",
                        "institution_revision", "window_transition",
                        "weight_reallocation_review"}
                        for cause in causes)
                    else "共同来源口径下仍成立的合作结构变化（新增/撤回）"
                ),
            }
        )
    return {
        "basis": "common_coverage_networks",
        "changed_edges": rows,
        "unchanged_edge_count": len(all_edges) - len(rows),
    }


def _attribute_edge(edge, before_works, after_works, before_contrib,
                    after_contrib, before_dict, after_dict, manual,
                    before_present, after_present):
    """对一条边的权重差做成果级归因。

    判定优先级：显式操作证据 > 结构化推断（词典/记录修订、窗口进出、撤回）>
    保守的未决标记。推断无法区分身份合并/拆分时不乱下结论，标记为待核。
    """
    causes = []
    old_ids = set(before_contrib.get(edge, {}))
    new_ids = set(after_contrib.get(edge, {}))
    changed_ids = sorted((new_ids - old_ids) | (old_ids - new_ids))

    for work_id in changed_ids:
        direction = "added" if work_id in new_ids else "removed"
        note = manual.get(work_id)
        if note:
            causes.append({
                "category": note["category"],
                "work_id": work_id,
                "direction": direction,
                "evidence": note,
            })
            continue
        inferred = _infer_cause(
            work_id, direction, before_works, after_works,
            before_dict, after_dict,
            before_present, after_present,
        )
        causes.append(inferred)

    if not causes:
        # 边仍由同一批成果贡献但权重变化：只可能来自机构集合/词典修订，
        # 正常情况下已在成果级捕获；留痕以便复核。
        causes.append({
            "category": "weight_reallocation_review",
            "direction": "changed",
            "edge": list(edge),
        })

    unique = []
    seen = set()
    for cause in sorted(causes, key=lambda item: (
            item.get("work_id", ""), item["category"])):
        key = (cause["category"], cause.get("work_id"))
        if key not in seen:
            seen.add(key)
            unique.append(cause)
    return unique


def _infer_cause(work_id, direction, before_works, after_works,
                 before_dict, after_dict,
                 before_present, after_present):
    before = before_works.get(work_id)
    after = after_works.get(work_id)
    base = {"work_id": work_id, "direction": direction}

    if direction == "added":
        if work_id in before_present:
            # 成果在前期发布中以 active 存在（即使被年份窗挡在网络外），
            # 本期入图 -> 时间窗进入，而不是新立项。
            return {**base, "category": "window_transition",
                    "detail": "active work enters the later year window"}
        if before is None:
            return {**base, "category": "work_added",
                    "records": sorted(after["records"])}
        if _dictionary_changes_edge(before, before_dict, after_dict):
            return {**base, "category": "institution_revision",
                    "records": sorted(set(before["records"])
                                      | set(after["records"])),
                    "before_names": _names(before, before_dict),
                    "after_names": _names(after, after_dict)}
        return {**base, "category": "identity_change_review",
                "detail": "same work id newly contributes this edge; "
                          "confirm merge decision in identity ledger",
                "records": sorted(after["records"])}

    # direction == removed
    if work_id in after_present:
        return {**base, "category": "window_transition",
                "detail": "active work leaves the later year window"}
    if after is None:
        return {**base, "category": "work_withdrawn",
                "records": sorted(before["records"])}
    if _dictionary_changes_edge(before, before_dict, after_dict):
        return {**base, "category": "institution_revision",
                "records": sorted(set(before["records"])
                                  | set(after["records"])),
                "before_names": _names(before, before_dict),
                "after_names": _names(after, after_dict)}
    return {**base, "category": "identity_change_review",
            "detail": "work stops contributing this edge; "
                      "confirm split decision in identity ledger",
            "records": sorted(before["records"])}


def _dictionary_changes_edge(work_entry, before_dict, after_dict):
    def resolve_all(dictionary):
        names = set()
        for raw_set in work_entry["institution_sets"]:
            for name in raw_set:
                if name and name.strip():
                    names.add(dictionary.resolve(name))
        return names

    return resolve_all(before_dict) != resolve_all(after_dict)


def _names(entry, dictionary):
    return sorted({
        dictionary.resolve(name)
        for raw_set in entry["institution_sets"]
        for name in raw_set
        if name and name.strip()
    })


def _coverage_warning(before_full, after_full, before_common, after_common):
    """量化全量与共同来源口径的差异，防止把新来源当作新增合作。"""
    def stats(net):
        return {
            "nodes": net["totals"]["node_count"],
            "edges": net["totals"]["edge_count"],
            "total_edge_weight": net["totals"]["total_edge_weight"]["exact"],
            "included_works": net["totals"]["included_work_count"],
        }

    return {
        "before_full": stats(before_full),
        "after_full": stats(after_full),
        "before_common": stats(before_common),
        "after_common": stats(after_common),
        "rule": (
            "全量网络的差异包含来源覆盖变化；只有共同来源网络的差异"
            "才能用于讨论真实合作变化。"
        ),
    }
