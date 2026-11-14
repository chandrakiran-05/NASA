"""FastAPI application factory.

Run:  uvicorn backend.main:app --reload        (docs at http://localhost:8000/docs)
"""
from __future__ import annotations

import logging
import time
import warnings
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from .ai.assistant import AIService
from .ai.llm import LocalLLM
from .api.routes import router
from .api.state import AppState
from .catalog.catalog import load_catalog
from .core.config import Settings, get_settings
from .core.errors import TrendDetectiveError
from .core.http import ResilientHTTP
from .jobs.manager import JobManager
from .storage.db import Database
from .storage.series_store import SeriesStore
from .timeseries.service import TimeSeriesService

VERSION = "1.0.0"
try:  # FastAPI >= 0.120 deprecates ORJSONResponse but it still works; keep output clean for students
    from fastapi.exceptions import FastAPIDeprecationWarning
    warnings.filterwarnings("ignore", category=FastAPIDeprecationWarning)
except ImportError:  # older FastAPI
    pass
log = logging.getLogger("etd")


def build_state(settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
                llm_transport: httpx.AsyncBaseTransport | None = None) -> AppState:
    settings.ensure_dirs()
    http = ResilientHTTP(settings, transport=transport)
    catalog = load_catalog(settings.data_dir)
    db = Database(settings.db_path)
    store = SeriesStore(settings.series_dir, db)
    ts = TimeSeriesService(settings, http, catalog, store)
    llm = LocalLLM(settings, transport=llm_transport)
    ai = AIService(settings, catalog, llm)
    return AppState(settings, http, catalog, db, store, ts, JobManager(db, settings.max_concurrent_jobs), llm, ai)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None,
               llm_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st = build_state(settings, transport, llm_transport)
        app.state.etd = st
        n = st.db.mark_stale_jobs()
        if n:
            log.warning("marked %d interrupted job(s) as error", n)
        t0 = time.perf_counter()
        from .analysis.kernels import warmup
        warmup()                                   # JIT-compile numerical kernels once
        from .ai import gazetteer
        gazetteer._index()                         # load the offline gazetteer once
        log.info("warm-up done in %.2fs", time.perf_counter() - t0)
        try:
            yield
        finally:
            await st.jobs.shutdown()
            await st.http.aclose()
            await st.llm.aclose()
            st.db.close()

    app = FastAPI(
        title=settings.app_name, version=VERSION, lifespan=lifespan, default_response_class=ORJSONResponse,
        description=("Select Earth-science variables, acquire them for a region from NASA/NOAA services, build "
                     "monthly time series, and test trends for significance (OLS with autocorrelation correction, "
                     "Mann-Kendall family, Sen's slope) with novel insights and an offline AI assistant."),
    )
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(TrendDetectiveError)
    async def etd_error(_: Request, exc: TrendDetectiveError):
        return ORJSONResponse(status_code=exc.status_code,
                              content={"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return ORJSONResponse(status_code=422, content={"error": {"code": "invalid_request",
                                                                  "message": "Request validation failed",
                                                                  "detail": {"errors": exc.errors()}}})

    app.include_router(router)
    return app


app = create_app()
