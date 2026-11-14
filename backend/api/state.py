"""Application state container (one per process), created in the FastAPI lifespan."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..ai.assistant import AIService
from ..ai.llm import LocalLLM
from ..catalog.catalog import Catalog
from ..core.config import Settings
from ..core.http import ResilientHTTP
from ..jobs.manager import JobManager
from ..storage.db import Database
from ..storage.series_store import SeriesStore
from ..timeseries.service import TimeSeriesService


@dataclass
class AppState:
    settings: Settings
    http: ResilientHTTP
    catalog: Catalog
    db: Database
    store: SeriesStore
    ts: TimeSeriesService
    jobs: JobManager
    llm: LocalLLM
    ai: AIService

    def result_key(self, kind: str, series_id: str, params: dict) -> str:
        h = hashlib.sha256(json.dumps({"k": kind, "s": series_id, "p": params}, sort_keys=True,
                                      default=str).encode()).hexdigest()[:24]
        return f"r_{h}"
