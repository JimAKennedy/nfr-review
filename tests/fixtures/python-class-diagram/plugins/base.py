"""Abstract plugin base class."""

from abc import ABC, abstractmethod


class Plugin(ABC):
    @abstractmethod
    def activate(self) -> None: ...

    @abstractmethod
    def deactivate(self) -> None: ...
