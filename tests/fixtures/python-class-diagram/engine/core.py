"""Core engine — uses Config, Logger, and Plugin via composition and parameters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging_pkg.base import Logger
    from plugins.base import Plugin

    from engine.config import Config


class Engine:
    _config: Config
    _logger: Logger
    _plugins: list

    def __init__(self, config: Config, logger: Logger) -> None:
        self._config = config
        self._logger = logger
        self._plugins = []

    def register_plugin(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)

    def start(self) -> None:
        self._logger.log("Engine starting")
        for p in self._plugins:
            p.activate()
