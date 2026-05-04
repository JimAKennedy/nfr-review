from __future__ import annotations

from typing import Generic, TypeVar

from nfr_review.protocols import Collector, Rule

T = TypeVar("T")


class Registry(Generic[T]):
    """In-memory registry keyed by a stable string id.

    Concrete singletons (`rule_registry`, `collector_registry`) live at module scope.
    """

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}

    def register(self, key: str, item: T) -> None:
        if key in self._items:
            raise ValueError(f"{self._kind} with id {key!r} is already registered")
        self._items[key] = item

    def get(self, key: str) -> T:
        try:
            return self._items[key]
        except KeyError as exc:
            raise KeyError(f"no {self._kind} registered with id {key!r}") from exc

    def all(self) -> list[T]:
        return list(self._items.values())

    def list(self) -> list[T]:
        return self.all()

    def ids(self) -> list[str]:  # type: ignore[valid-type]
        return list(self._items.keys())

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._items

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


rule_registry: Registry[Rule] = Registry("rule")
collector_registry: Registry[Collector] = Registry("collector")


def list_rules() -> list[Rule]:
    return rule_registry.all()


def list_collectors() -> list[Collector]:
    return collector_registry.all()


__all__ = [
    "Registry",
    "collector_registry",
    "list_collectors",
    "list_rules",
    "rule_registry",
]
