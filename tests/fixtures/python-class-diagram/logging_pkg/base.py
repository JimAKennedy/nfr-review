"""Logger protocol/interface."""

from typing import Protocol


class Logger(Protocol):
    def log(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...
