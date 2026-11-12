"""网络分析配置：发布版、年份窗、权重口径、算法参数全部显式且可摘要。"""

from fractions import Fraction
from ..contracts import integer, fail, digest, canonical
from .rational import to_rational

WEIGHT_SCHEMES = ("count", "fractional")


class NetworkConfig:
    """一次网络构建与社区发现的完整口径。

    weight_scheme:
      - ``count``：每项 k 机构成果在其每个机构对上整计一条边（权重 +1）；
      - ``fractional``：每个机构对只分配 1/C(k,2) 的权重，单成果总边权恒为 1。
    """

    def __init__(
        self,
        *,
        release,
        year_from,
        year_to,
        weight_scheme="count",
        max_collaborators=50,
        resolution=Fraction(1),
        seed=7,
        tolerance=Fraction(0),
        max_passes=100,
        max_levels=50,
        restarts=1,
        sources=None,
        dictionary_revision=None,
        description="",
    ):
        if not isinstance(release, str) or not release:
            fail("input", "release must be a nonempty identifier")
        integer(year_from, 1900, 2200)
        integer(year_to, 1900, 2200)
        if year_from > year_to:
            fail("input", "year window is reversed")
        if weight_scheme not in WEIGHT_SCHEMES:
            fail("input", "weight_scheme must be count or fractional")
        integer(max_collaborators, 2, 10000)
        integer(seed, 0, 2**32 - 1)
        integer(max_passes, 1, 10000)
        integer(max_levels, 1, 1000)
        integer(restarts, 1, 1000)
        resolution = to_rational(resolution)
        tolerance = to_rational(tolerance)
        if resolution <= 0:
            fail("input", "resolution must be positive")
        if sources is not None:
            if not isinstance(sources, (list, tuple)) or not sources:
                fail("input", "sources filter must be a nonempty list")
            sources = sorted({str(item) for item in sources})
        self.release = release
        self.year_from = year_from
        self.year_to = year_to
        self.weight_scheme = weight_scheme
        self.max_collaborators = max_collaborators
        self.resolution = resolution
        self.seed = seed
        self.tolerance = tolerance
        self.max_passes = max_passes
        self.max_levels = max_levels
        self.restarts = restarts
        self.sources = sources
        self.dictionary_revision = dictionary_revision
        self.description = description

    def to_dict(self):
        return {
            "release": self.release,
            "year_window": [self.year_from, self.year_to],
            "weight_scheme": self.weight_scheme,
            "max_collaborators": self.max_collaborators,
            "resolution": str(self.resolution),
            "seed": self.seed,
            "tolerance": str(self.tolerance),
            "max_passes": self.max_passes,
            "max_levels": self.max_levels,
            "restarts": self.restarts,
            "sources": self.sources,
            "dictionary_revision": self.dictionary_revision,
            "description": self.description,
            "tie_breaking": (
                "候选社区按社区编号升序评估；严格大于当前最优增益才替换，"
                "因此等增益平局保留最小编号社区；节点顺序由种子经确定性"
                "随机数发生器生成并记录于结果。"
            ),
            "stop_rules": (
                "局部移动阶段一轮内无严格增益移动则停止；"
                "聚合后模块度不再严格增加（受 tolerance 控制）则停止；"
                "达到 max_passes/max_levels 上限也停止。"
            ),
        }

    def digest(self):
        # 描述性文字不影响计算结果，不进入口径摘要。
        payload = self.to_dict()
        payload.pop("description", None)
        payload.pop("tie_breaking", None)
        payload.pop("stop_rules", None)
        return digest(payload)

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict):
            fail("input", "config object required")
        allowed = {
            "release",
            "year_window",
            "weight_scheme",
            "max_collaborators",
            "resolution",
            "seed",
            "tolerance",
            "max_passes",
            "max_levels",
            "restarts",
            "sources",
            "dictionary_revision",
            "description",
            "tie_breaking",
            "stop_rules",
        }
        unknown = set(payload) - allowed
        if unknown:
            fail("input", "unknown config fields", extra=sorted(unknown))
        window = payload["year_window"]
        if not isinstance(window, list) or len(window) != 2:
            fail("input", "year_window must contain two years")
        return cls(
            release=payload["release"],
            year_from=window[0],
            year_to=window[1],
            weight_scheme=payload.get("weight_scheme", "count"),
            max_collaborators=payload.get("max_collaborators", 50),
            resolution=Fraction(payload.get("resolution", "1")),
            seed=payload.get("seed", 7),
            tolerance=Fraction(payload.get("tolerance", "0")),
            max_passes=payload.get("max_passes", 100),
            max_levels=payload.get("max_levels", 50),
            restarts=payload.get("restarts", 1),
            sources=payload.get("sources"),
            dictionary_revision=payload.get("dictionary_revision"),
            description=payload.get("description", ""),
        )

    def __eq__(self, other):
        return isinstance(other, NetworkConfig) and canonical(
            self.to_dict()
        ) == canonical(other.to_dict())
