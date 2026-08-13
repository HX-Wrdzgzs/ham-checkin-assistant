"""词典缓存：从 SQLite 加载别名并归一化 key（去连字符/空格、小写）。"""
from __future__ import annotations

from database.models import Alias
from database.repository import Repository


def norm_key(s: str) -> str:
    return (s or "").strip().lower().replace("-", "").replace(" ", "")


class AliasStore:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.qth: dict[str, Alias] = {}
        self.device: dict[str, Alias] = {}
        self.antenna: dict[str, Alias] = {}
        self.power: dict[str, Alias] = {}
        self.reload()

    def reload(self) -> None:
        self.qth = self._build("qth")
        self.device = self._build("device")
        self.antenna = self._build("antenna")
        self.power = self._build("power")

    def _build(self, kind: str) -> dict[str, Alias]:
        out: dict[str, Alias] = {}
        for a in self.repo.get_aliases(kind):
            out[norm_key(a.alias)] = a
        return out

    def lookup(self, kind: str, token: str) -> Alias | None:
        d = {"qth": self.qth, "device": self.device, "antenna": self.antenna, "power": self.power}[kind]
        return d.get(norm_key(token))

    def options(self, kind: str) -> list[tuple[str, str]]:
        """(归一化key, 标准值) 列表，用于模糊匹配。"""
        d = {"qth": self.qth, "device": self.device, "antenna": self.antenna, "power": self.power}[kind]
        return [(k, v.standard_value) for k, v in d.items()]
