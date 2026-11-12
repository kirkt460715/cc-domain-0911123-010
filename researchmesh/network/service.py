"""网络分析服务门面。

既可挂到 :class:`researchmesh.service.ResearchMesh` 上读取不可变发布，
也可以脱离数据库，直接对显式成果表运行纯函数分析。
所有写盘操作走 network.bundle，配置与词典摘要保证可重取。
"""

from pathlib import Path
from fractions import Fraction

from ..contracts import identifier, integer, fail, decode
from .config import NetworkConfig
from .dictionary import FixedDictionary
from .builder import NetworkBuilder
from .modularity import analyze
from .compare import compare_periods
from .bundle import save_bundle, verify_bundle, rerun_bundle
from .adapter import work_table_from_release


class NetworkAnalytics:
    def __init__(self, mesh=None):
        self.mesh = mesh

    # ---- 发布版取数 --------------------------------------------------
    def release_table(self, release, institution_members):
        if self.mesh is None:
            fail("state", "analytics facade has no ResearchMesh backend")
        identifier(release)
        payload = self.mesh.releases.get(release)["payload"]
        return work_table_from_release(payload, institution_members)

    def _dictionary(self, mapping=None, revision=None):
        if mapping is None and self.mesh is not None:
            rows = self.mesh.dictionary.list("institution")["rows"]
            mapping = {row["alias"]: row["target"] for row in rows}
            revision = self.mesh.store.revision("dictionary")
        return FixedDictionary(mapping or {}, revision=revision)

    # ---- 单期网络 ----------------------------------------------------
    def analyze_release(
        self, release, institution_members, year_from, year_to, *,
        weight_scheme="count", resolution="1", seed=7, sources=None,
        max_collaborators=50, restarts=1, dictionary_mapping=None,
        dictionary_revision=None,
    ):
        table = self.release_table(release, institution_members)
        dictionary = self._dictionary(dictionary_mapping, dictionary_revision)
        config = NetworkConfig(
            release=release, year_from=year_from, year_to=year_to,
            weight_scheme=weight_scheme,
            resolution=Fraction(resolution), seed=integer(seed, 0, 2**32 - 1),
            sources=sources, max_collaborators=max_collaborators,
            restarts=integer(restarts, 1, 1000),
            dictionary_revision=dictionary.revision,
        )
        return analyze(
            NetworkBuilder(config, dictionary).build(table["rows"]), config
        )

    def analyze_table(self, rows, config, dictionary):
        if not isinstance(dictionary, FixedDictionary) or \
                not isinstance(config, NetworkConfig):
            fail("input", "analyze_table requires NetworkConfig and FixedDictionary")
        from .model import parse_work_table
        parsed = parse_work_table(rows)
        network = NetworkBuilder(config, dictionary).build(parsed)
        return analyze(network, config)

    # ---- 两期比较 ----------------------------------------------------
    def compare_releases(
        self, before_release, after_release,
        before_members, after_members,
        before_window, after_window, *,
        weight_scheme="fractional", resolution="1", seed=7, restarts=1,
        before_dictionary=None, after_dictionary=None, attribution=None,
    ):
        before_table = self.release_table(
            before_release, before_members)["rows"]
        after_table = self.release_table(
            after_release, after_members)["rows"]
        before_dict = self._dictionary(*self._dict_args(before_dictionary))
        after_dict = self._dictionary(*self._dict_args(after_dictionary))
        before_cfg = NetworkConfig(
            release=before_release, year_from=before_window[0],
            year_to=before_window[1], weight_scheme=weight_scheme,
            resolution=Fraction(resolution), seed=seed,
            restarts=integer(restarts, 1, 1000),
            dictionary_revision=before_dict.revision,
        )
        after_cfg = NetworkConfig(
            release=after_release, year_from=after_window[0],
            year_to=after_window[1], weight_scheme=weight_scheme,
            resolution=Fraction(resolution), seed=seed,
            restarts=integer(restarts, 1, 1000),
            dictionary_revision=after_dict.revision,
        )
        return compare_periods(
            before_table, after_table, before_cfg, after_cfg,
            before_dict, after_dict, attribution=attribution or {},
        )

    @staticmethod
    def _dict_args(value):
        if value is None:
            return (None, None)
        return (value.get("mapping"), value.get("revision"))

    # ---- 持久化 ------------------------------------------------------
    def export_bundle(self, path, release, release_digest, rows, dictionary,
                      config, notes=""):
        return save_bundle(
            path, release, release_digest, rows, dictionary, config, notes=notes
        )

    @staticmethod
    def verify_bundle_file(path):
        return verify_bundle(decode(Path(path).read_text("utf-8")))

    @staticmethod
    def rerun_bundle_file(path):
        return rerun_bundle(path)
