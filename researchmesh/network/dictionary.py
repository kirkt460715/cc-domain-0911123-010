"""固定机构别名词典。

构建网络时词典不可变：每条别名按固定映射逐跳解析（检测环与超长链），
未登录名称原样保留。词典整体带摘要，结果记录所用词典版本以便重取。
"""

from ..contracts import bounded_text, fail, digest, integer
from ..normalization.text import fold


class FixedDictionary:
    def __init__(self, mapping=None, *, max_chain=100, revision=None):
        self.max_chain = integer(max_chain, 1, 10000)
        self.revision = revision
        self._mapping = {}
        self._unresolved = set()
        for alias, target in (mapping or {}).items():
            self.add(alias, target)
        # 预先解析一遍以暴露环与超长链，并固定 unresolved 集合。
        for alias in sorted(self._mapping):
            self.resolve(alias)

    def add(self, alias, target):
        alias = fold(bounded_text(alias, 500))
        target = fold(bounded_text(target, 500))
        if not alias or not target:
            fail("input", "dictionary alias and target must be nonempty")
        if alias == target:
            fail("input", "dictionary alias and target must differ")
        self._mapping[alias] = target
        self._unresolved.discard(alias)

    def resolve(self, name):
        """返回归一化机构名；未登录名称原样返回并登记。"""
        current = fold(bounded_text(name, 500))
        if not current:
            fail("input", "institution name must contain letters or numbers")
        start = current
        visited = []
        seen = set()
        while current in self._mapping:
            if current in seen:
                fail(
                    "cycle",
                    "fixed dictionary contains an alias cycle",
                    entry=start,
                    path=visited + [current],
                )
            seen.add(current)
            visited.append(current)
            if len(visited) > self.max_chain:
                fail("capacity", "alias chain too long", entry=start)
            current = self._mapping[current]
        if not visited:
            self._unresolved.add(current)
        return current

    def unresolved(self):
        return sorted(self._unresolved)

    def to_dict(self):
        return {
            "kind": "institution",
            "revision": self.revision,
            "max_chain": self.max_chain,
            "mapping": {key: self._mapping[key] for key in sorted(self._mapping)},
        }

    def digest(self):
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict) or "mapping" not in payload:
            fail("input", "dictionary object requires mapping")
        return cls(
            payload["mapping"],
            max_chain=payload.get("max_chain", 100),
            revision=payload.get("revision"),
        )
