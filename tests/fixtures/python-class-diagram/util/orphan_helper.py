"""Orphan class — no relationships to other classes in the diagram."""


class OrphanHelper:
    _cache: dict

    def __init__(self) -> None:
        self._cache = {}

    def clear(self) -> None:
        self._cache.clear()
