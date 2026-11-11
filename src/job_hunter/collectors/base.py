from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Collector(ABC):
    source: str

    @abstractmethod
    def collect(self) -> list[dict[str, Any]]:
        """Return source-native job objects or raise on a source-wide failure."""
