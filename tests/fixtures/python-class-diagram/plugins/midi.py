"""MIDI plugin — extends Plugin, uses Config."""

from __future__ import annotations

from typing import TYPE_CHECKING

from plugins.base import Plugin

if TYPE_CHECKING:
    from engine.config import Config


class MidiPlugin(Plugin):
    _config: Config
    _channel: int

    def __init__(self, config: Config, channel: int = 1) -> None:
        self._config = config
        self._channel = channel

    def activate(self) -> None:
        pass

    def deactivate(self) -> None:
        pass

    def send_note(self, note: int, velocity: int) -> None:
        pass
