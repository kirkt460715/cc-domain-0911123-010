"""分析包的保存、校验与重取。

一个包包含：输入成果表（带来源发布摘要）、固定词典、网络/算法配置、
结果与各部分摘要。重取时用相同输入重跑并逐项比对摘要，
任何输入或口径被篡改都会在校验中暴露。
"""

import os
import tempfile
from pathlib import Path

from ..contracts import canonical, decode, digest, fail, fields
from .config import NetworkConfig
from .dictionary import FixedDictionary
from .model import parse_work_table, table_digest
from .builder import NetworkBuilder
from .modularity import analyze


BUNDLE_VERSION = 1


def _write_json(path, payload):
    target = Path(path)
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        fail("path", "bundle destination must be a new file in an existing directory")
    content = canonical(payload).encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix=".mesh-net-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            fail("path", "bundle destination appeared concurrently")
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(target), "bytes": len(content), "digest": digest(payload)}


def build_bundle(release_id, release_digest, rows, dictionary, config, *,
                 notes=""):
    """执行一次分析并打包（不写盘）。"""
    table = parse_work_table(rows)
    network = NetworkBuilder(config, dictionary).build(table)
    result = analyze(network, config)
    payload = {
        "bundle_type": "researchmesh-network-analysis",
        "bundle_version": BUNDLE_VERSION,
        "release": {
            "id": release_id,
            "digest": release_digest,
        },
        "work_table": table,
        "work_table_digest": table_digest(table),
        "dictionary": dictionary.to_dict(),
        "dictionary_digest": dictionary.digest(),
        "config": config.to_dict(),
        "config_digest": config.digest(),
        "result": result,
        "notes": notes,
    }
    payload["bundle_digest"] = digest(
        {key: value for key, value in payload.items() if key != "bundle_digest"}
    )
    return payload


def save_bundle(path, release_id, release_digest, rows, dictionary, config, *,
                notes=""):
    payload = build_bundle(release_id, release_digest, rows, dictionary, config,
                           notes=notes)
    written = _write_json(path, payload)
    return {**written, "bundle_digest": payload["bundle_digest"]}


def load_bundle(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000_000:
        fail("path", "bundle must be a bounded regular local file")
    payload = decode(path.read_text("utf-8"))
    verify_bundle(payload)
    return payload


def verify_bundle(payload):
    if not isinstance(payload, dict):
        fail("input", "bundle object required")
    fields(
        payload,
        {
            "bundle_type", "bundle_version", "release", "work_table",
            "work_table_digest", "dictionary", "dictionary_digest",
            "config", "config_digest", "result", "notes", "bundle_digest",
        },
        {
            "bundle_type", "bundle_version", "release", "work_table",
            "work_table_digest", "dictionary", "dictionary_digest",
            "config", "config_digest", "result", "bundle_digest",
        },
    )
    if payload["bundle_type"] != "researchmesh-network-analysis" or \
            payload["bundle_version"] != BUNDLE_VERSION:
        fail("version", "unknown network bundle format")
    expected_digest = digest(
        {key: value for key, value in payload.items() if key != "bundle_digest"}
    )
    if expected_digest != payload["bundle_digest"]:
        fail("integrity", "bundle content changed after saving")
    if table_digest(payload["work_table"]) != payload["work_table_digest"]:
        fail("integrity", "work table digest differs")
    dictionary = FixedDictionary.from_dict(payload["dictionary"])
    if dictionary.digest() != payload["dictionary_digest"]:
        fail("integrity", "dictionary digest differs")
    config = NetworkConfig.from_dict(payload["config"])
    if config.digest() != payload["config_digest"]:
        fail("integrity", "config digest differs")
    rerun = rerun_payload(payload)
    if rerun["network_digest"] != payload["result"]["network_digest"]:
        fail("integrity", "rerun produced a different network")
    if rerun["communities_result"]["modularity"]["exact"] != \
            payload["result"]["communities_result"]["modularity"]["exact"]:
        fail("integrity", "rerun produced a different modularity")
    if rerun["communities_result"]["partition"] != \
            payload["result"]["communities_result"]["partition"]:
        fail("integrity", "rerun produced a different community partition")
    return {
        "verified": True,
        "bundle_digest": payload["bundle_digest"],
        "release": payload["release"]["id"],
        "nodes": rerun["totals"]["node_count"],
        "edges": rerun["totals"]["edge_count"],
        "modularity": rerun["communities_result"]["modularity"]["exact"],
    }


def rerun_payload(payload):
    config = NetworkConfig.from_dict(payload["config"])
    dictionary = FixedDictionary.from_dict(payload["dictionary"])
    table = parse_work_table(payload["work_table"])
    network = NetworkBuilder(config, dictionary).build(table)
    return analyze(network, config)


def rerun_bundle(path):
    """从磁盘重取：校验并用包内输入完整重跑，返回新结果与校验报告。"""
    payload = load_bundle(path)
    report = verify_bundle(payload)
    return {"verification": report, "result": rerun_payload(payload)}
