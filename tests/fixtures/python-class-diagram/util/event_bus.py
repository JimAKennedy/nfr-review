"""Event bus — uses Plugin as parameter type only (dependency, not composition)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins.base import Plugin


class EventBus:
    def dispatch(self, plugin: Plugin, event: str) -> None:
        pass
