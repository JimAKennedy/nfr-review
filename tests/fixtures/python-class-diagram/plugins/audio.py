"""Audio plugin with an inner class."""

from __future__ import annotations

from plugins.base import Plugin


class AudioPlugin(Plugin):
    _volume: float

    def __init__(self) -> None:
        self._volume = 0.8

    def activate(self) -> None:
        pass

    def deactivate(self) -> None:
        pass

    def set_volume(self, level: float) -> None:
        self._volume = level

    class Preset:
        """Inner class representing an audio preset."""

        name: str
        gain: float

        def __init__(self, name: str, gain: float) -> None:
            self.name = name
            self.gain = gain
