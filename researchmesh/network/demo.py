"""网络分析端到端合成演练。

教学场景：
* 两个稠密合作团体（A/B/C 与 D/E/F），由一条 C-D 桥边相连：
  连通分量为 1 个，但模块度优化得到 2 个社区；
* 2026 年接入新来源 extra，只带来重复副本与来源增补：
  全量网络变化，而固定共同来源网络保持稳定，证明不能把新来源当新增合作；
* 同时保留身份合并、身份拆分、机构修订（词典修订与原始记录修订两种）、
  成果撤回与时间窗进出的对照证据；
* 缺机构、超大联合成果、身份冲突均作为可追溯排除项，不静默丢弃。
"""

import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from . import (
    FixedDictionary,
    NetworkConfig,
    NetworkBuilder,
    compare_periods,
    save_bundle,
    load_bundle,
)
from .modularity import analyze, louvain, connected_components


def _row(source, local_id, work_id, year, institutions, active=True):
    return {
        "record_key": source + ":" + local_id,
        "work_id": work_id,
        "source": source,
        "year": year,
        "institutions": institutions,
        "active": active,
    }


def _clique_rows(prefix, year, pair, index):
    left, right = pair
    return [
        _row("lab", prefix + "-" + str(index), prefix + str(index), year,
             [left, right])
    ]


LEFT_PAIRS = [("A", "B"), ("B", "C"), ("C", "A")]
RIGHT_PAIRS = [("D", "E"), ("E", "F"), ("F", "D")]


def period_tables():
    # ---- 2025 窗口（2024-2025）的发布版 r2025 ----
    before = []
    for index, pair in enumerate(LEFT_PAIRS * 2):
        before += _clique_rows("L", 2025, pair, index)
    for index, pair in enumerate(RIGHT_PAIRS * 2):
        before += _clique_rows("R", 2025, pair, index)
    before.append(_row("lab", "bridge-1", "bridge", 2025, ["C", "D"]))
    # 单机构成果：只贡献节点，不产生边。
    before.append(_row("lab", "solo-1", "solo-a", 2025, ["A"]))
    before.append(_row("lab", "iso-1", "solo-g", 2025, ["G"]))
    # 三类可追溯排除项。
    before.append(_row("lab", "noinst-1", "noinst", 2025, []))
    before.append(_row("lab", "big-1", "bigcollab", 2025,
                       ["A", "B", "C", "D", "E", "F"]))
    before.append(_row("lab", "conflict-1", "conflict-year", 2025, ["A", "B"]))
    before.append(_row("registry", "conflict-1", "conflict-year", 2024,
                       ["A", "B"]))
    # 时间窗之外（2026 成果在 2025 窗口不可见）。
    before.append(_row("lab", "future-1", "future-work", 2026, ["A", "E"]))
    # 身份合并的素材：前期是两个独立成果。
    before.append(_row("lab", "merge-a", "merge-x", 2025, ["A", "B"]))
    before.append(_row("factory", "merge-b", "merge-y", 2025, ["A", "B"]))

    # ---- 2026 窗口（2025-2026）的发布版 r2026 ----
    after = []
    for index, pair in enumerate(LEFT_PAIRS * 2):
        after += _clique_rows("L", 2025, pair, index)
    for index, pair in enumerate(RIGHT_PAIRS * 2):
        after += _clique_rows("R", 2025, pair, index)
    after.append(_row("lab", "bridge-1", "bridge", 2025, ["C", "D"]))
    after.append(_row("lab", "solo-1", "solo-a", 2025, ["A"]))
    after.append(_row("lab", "iso-1", "solo-g", 2025, ["G"]))
    after.append(_row("lab", "noinst-1", "noinst", 2025, []))
    after.append(_row("lab", "big-1", "bigcollab", 2025,
                      ["A", "B", "C", "D", "E", "F"]))
    after.append(_row("lab", "conflict-1", "conflict-year", 2025, ["A", "B"]))
    after.append(_row("registry", "conflict-1", "conflict-year", 2026,
                      ["A", "B"]))
    after.append(_row("lab", "future-1", "future-work", 2026, ["A", "E"]))

    # 真实新增合作：2026 新成果。
    after.append(_row("lab", "newedge-1", "new-edge", 2026, ["B", "E"]))
    # 成果撤回：2025 有、2026 完整快照中消失（用 inactive 记录留痕）。
    after.append(_row("lab", "gone-1", "withdrawn-work", 2025, ["B", "C"],
                      active=False))
    before.append(_row("lab", "gone-1", "withdrawn-work", 2025, ["B", "C"]))

    # 身份合并：merge-x 与 merge-y 在 r2026 融合为 merged-work。
    after.append(_row("lab", "merge-a", "merged-work", 2025, ["A", "B"]))
    after.append(_row("factory", "merge-b", "merged-work", 2025, ["A", "B"]))
    # 身份拆分：split-work 在 r2026 被拆成两个独立身份。
    before.append(_row("lab", "split-1", "split-work", 2025, ["E", "F"]))
    after.append(_row("lab", "split-1a", "split-part-1", 2025, ["E", "F"]))
    after.append(_row("lab", "split-1b", "split-part-2", 2025, ["E", "F"]))

    # 机构修订（一）：词典把别名并入规范名，原始记录不变。
    before.append(_row("lab", "dict-1", "dict-revision", 2025, ["A2", "B"]))
    after.append(_row("lab", "dict-1", "dict-revision", 2025, ["A2", "B"]))
    # 机构修订（二）：原始记录本身改写机构。
    before.append(_row("lab", "raw-1", "raw-revision", 2025, ["B", "F"]))
    after.append(_row("lab", "raw-1", "raw-revision", 2025, ["B", "E"]))

    # ---- 新来源 extra：仅覆盖 2026，含重复副本与来源增补 ----
    # 重复副本：同一 work_id 的第二来源记录（年份/机构必须与原成果一致，
    # 否则构成身份冲突），图中只能贡献一次。
    after.append(_row("extra", "dup-bridge", "bridge", 2025, ["C", "D"]))
    after.append(_row("extra", "dup-new", "new-edge", 2026, ["B", "E"]))
    # 来源增补：extra 独有的新成果与新机构 H。
    after.append(_row("extra", "only-1", "extra-only", 2026, ["F", "H"]))
    return before, after


def dictionaries():
    before_dict = FixedDictionary(revision=3)
    after_dict = FixedDictionary(
        {"a2": "A"}, revision=4
    )  # 修订：A2 并入 A
    return before_dict, after_dict


def attribution_evidence():
    return {
        "new-edge": {"category": "work_added", "reason": "2026 年新立项成果"},
        "withdrawn-work": {
            "category": "work_withdrawn",
            "reason": "完整来源快照撤回，未在 r2026 出现",
        },
        "future-work": {
            "category": "window_transition",
            "reason": "成果年份 2026，随年份窗从 2025 窗进入 2026 窗",
        },
        "merged-work": {
            "category": "identity_merge",
            "reason": "人工合并决定 merge-x + merge-y -> merged-work",
        },
        "split-part-1": {
            "category": "identity_split",
            "reason": "人工拆分决定 split-work -> split-part-1/2",
        },
        "split-part-2": {
            "category": "identity_split",
            "reason": "人工拆分决定 split-work -> split-part-1/2",
        },
        "dict-revision": {
            "category": "institution_revision",
            "reason": "词典修订 A2 -> A（revision 3 -> 4）",
        },
        "raw-revision": {
            "category": "institution_revision",
            "reason": "来源记录修订：机构 F 改为 E",
        },
        "extra-only": {
            "category": "source_coverage",
            "reason": "仅新来源 extra 提供，共同来源口径下不可见",
        },
    }


def run(output_dir=None):
    before_rows, after_rows = period_tables()
    before_dict, after_dict = dictionaries()
    before_cfg = NetworkConfig(
        release="r2025", year_from=2024, year_to=2025,
        weight_scheme="fractional", seed=7,
        dictionary_revision=3, description="2025 窗口（含 2024 历史年）",
    )
    after_cfg = NetworkConfig(
        release="r2026", year_from=2025, year_to=2026,
        weight_scheme="fractional", seed=7,
        dictionary_revision=4, description="2026 窗口",
    )

    comparison = compare_periods(
        before_rows, after_rows, before_cfg, after_cfg,
        before_dict, after_dict,
        attribution=attribution_evidence(),
    )

    before_common = comparison["periods"]["before"]["common_coverage"]
    after_common = comparison["periods"]["after"]["common_coverage"]
    after_full = comparison["periods"]["after"]["full"]

    # 核心断言：桥边图里连通分量与社区不是一回事。
    components = connected_components(
        [n["id"] for n in after_common["nodes"]],
        {(e["source_node"], e["target_node"]):
         Fraction(e["weight"]["exact"]) for e in after_common["edges"]},
    )
    community = after_common["communities_result"]
    assert len(components) == 2, "桥边连通主体 + 孤立点 g"
    main_component = max(components, key=len)
    assert set(main_component) == set("abcdef"), main_component
    # 主连通分量（a-f 经 c-d 桥相连）是 1 个，但模块度优化把它分成 2 个社区；
    # 孤立点 g 各自成社区，因此总计 3 个社区、2 个连通分量。
    assert len(community["communities"]) == 3, community["stop_reason"]
    labels = community["partition"]
    assert labels["a"] == labels["b"] == labels["c"]
    assert labels["d"] == labels["e"] == labels["f"]
    assert labels["g"] not in (labels["a"], labels["d"])
    assert labels["c"] != labels["d"], "桥边两端分属不同社区"
    assert after_common["components_equal_communities"] is False
    assert Fraction(community["modularity"]["exact"]) > 0

    # 新来源只改变全量网络，不改变共同来源网络。
    assert after_full["totals"]["edge_count"] > \
        after_common["totals"]["edge_count"]
    assert comparison["periods"]["before"]["common_coverage"][
        "network_digest"
    ] != after_common["network_digest"]

    # 确定性：相同（共同来源）口径重跑，网络与社区逐位一致。
    common_cfg = NetworkConfig(
        release="r2026", year_from=2025, year_to=2026,
        weight_scheme="fractional", seed=7,
        sources=comparison["common_sources"], dictionary_revision=4,
    )
    rerun = analyze(
        NetworkBuilder(common_cfg, after_dict).build(after_rows), common_cfg
    )
    assert rerun["communities_result"]["partition"] == community["partition"]
    # 输入表与口径一致时完整指纹一致；结构摘要在任意共同来源对照下都稳定。
    assert rerun["structure_digest"] == after_common["structure_digest"]

    # 孤立点与无边图也有确定结果。
    edgeless = louvain(["x", "y"], {}, resolution=Fraction(1), seed=7)
    assert edgeless["stop_reason"] == "edgeless_graph_each_node_own_community"
    assert edgeless["modularity"]["exact"] == "0"
    assert set(edgeless["partition"].values()) == {"C1", "C2"}

    summary = {
        "common_sources": comparison["common_sources"],
        "bridge_case": {
            "connected_components": [sorted(c) for c in components],
            "component_count": len(components),
            "community_count": len(community["communities"]),
            "modularity": community["modularity"],
            "stop_reason": community["stop_reason"],
            "resolution": community["resolution"],
            "seed": community["seed"],
            "note": "一个连通分量（A-F 经 C-D 桥相连）被模块度优化分为两个社区",
        },
        "coverage_contrast": comparison["coverage_warning"],
        "community_matching": {
            "matches": comparison["community_matching"]["matches"],
            "unmatched_before":
                comparison["community_matching"]["unmatched_before"],
            "unmatched_after":
                comparison["community_matching"]["unmatched_after"],
            "splits": comparison["community_matching"]["splits"],
            "merges": comparison["community_matching"]["merges"],
        },
        "exclusions_before": before_common["exclusions"],
        "exclusions_after": after_common["exclusions"],
        "edge_change_count": len(
            comparison["edge_differences"]["changed_edges"]
        ),
        "edge_attribution_categories": sorted({
            cause["category"]
            for edge in comparison["edge_differences"]["changed_edges"]
            for cause in edge["attribution"]
        }),
    }

    written = []
    if output_dir is not None:
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        bundle_path = folder / "network-r2026-common.json"
        written.append(save_bundle(
            bundle_path, "r2026", "demo-release-digest",
            after_rows, after_dict, common_cfg,
            notes="共同来源覆盖下的 2026 窗口分析包",
        ))
        (folder / "period-comparison.json").write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True),
            "utf-8",
        )
        (folder / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            "utf-8",
        )
        # 从磁盘重取并校验：分区与模块度必须和内存结果一致。
        reloaded = load_bundle(bundle_path)
        assert reloaded["result"]["communities_result"]["partition"] == \
            community["partition"]
        assert reloaded["result"]["communities_result"]["modularity"] == \
            community["modularity"]
        summary["reloaded_bundle_digest"] = reloaded["bundle_digest"]
    return {"summary": summary, "comparison": comparison, "files": written}


if __name__ == "__main__":
    with TemporaryDirectory() as folder:
        outcome = run(folder)
        print(json.dumps(outcome["summary"], ensure_ascii=False,
                         indent=2, sort_keys=True))
        print("written:", [item["path"] for item in outcome["files"]])
