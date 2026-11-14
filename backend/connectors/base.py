"""Common connector interface: fetch(variable, region, start, end) -> RawSeries."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable

from ..core.config import Settings
from ..core.geometry import Region
from ..core.http import ResilientHTTP
from ..timeseries.model import RawSeries

ProgressFn = Callable[[float, str], Awaitable[None]]


async def _noop(_p: float, _m: str) -> None:
    return None


@dataclass
class FetchRequest:
    variable: dict                 # catalog entry
    region: Region
    start: date
    end: date
    options: dict = field(default_factory=dict)


class Connector(ABC):
    name: str = "base"
    supports_point: bool = True
    supports_area: bool = True

    def __init__(self, settings: Settings, http: ResilientHTTP):
        self.s = settings
        self.http = http

    @abstractmethod
    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries: ...

    async def health(self) -> dict:
        return {"connector": self.name, "status": "unknown"}
