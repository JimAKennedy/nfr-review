"""Console logger — implements Logger protocol."""

from logging_pkg.base import Logger


class ConsoleLogger(Logger):
    _prefix: str

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def log(self, message: str) -> None:
        print(f"{self._prefix}{message}")  # noqa: T201

    def error(self, message: str) -> None:
        print(f"{self._prefix}ERROR: {message}")  # noqa: T201
