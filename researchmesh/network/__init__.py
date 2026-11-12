"""机构合作网络分析子系统。

只依赖 Python 标准库；核心计算为纯函数，输入与配置全部显式传入，
权重内部使用 :class:`fractions.Fraction` 精确表示，展示用小数单独存放。
"""

from .dictionary import FixedDictionary
from .config import NetworkConfig
from .model import parse_work_table, table_digest
from .builder import NetworkBuilder
from .modularity import connected_components, modularity, louvain, louvain_restarts
from .matching import match_communities
from .compare import compare_periods
from .bundle import save_bundle, load_bundle, verify_bundle, rerun_bundle

__all__ = [
    "FixedDictionary",
    "NetworkConfig",
    "parse_work_table",
    "table_digest",
    "NetworkBuilder",
    "connected_components",
    "modularity",
    "louvain",
    "louvain_restarts",
    "match_communities",
    "compare_periods",
    "save_bundle",
    "load_bundle",
    "verify_bundle",
    "rerun_bundle",
]
