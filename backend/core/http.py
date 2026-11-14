"""Resilient async HTTP: retries with Retry-After, jittered exponential backoff,
per-host token-bucket rate limits, and a content-addressed raw response cache.

Every upstream call goes through `ResilientHTTP.request`, so 429 handling and caching are
the same for Giovanni, AppEEARS, NCEI, CDO and CMR.
"""
from __future__ import annotations

import asyncio
import contextvars
import email.utils
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import Settings
from .errors import UpstreamError

log = logging.getLogger("etd.http")

RETRY_STATUS = {429, 500, 502, 503, 504}
# set by TimeSeriesService.build_series(refresh=True): re-download instead of serving the raw cache
BYPASS_CACHE: contextvars.ContextVar[bool] = contextvars.ContextVar("bypass_cache", default=False)
# headers that must never end up in cache keys or provenance
SECRET_HEADERS = {"authorization", "token", "cookie"}


class TokenBucket:
    """Simple async token bucket: `rate` requests per second, burst = rate."""

    def __init__(self, rate: float):
        self.rate = rate
        self.capacity = max(rate, 1.0)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


@dataclass
class CachedResponse:
    status_code: int
    content: bytes
    headers: dict
    url: str
    retrieved_at: str
    from_cache: bool

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(value)
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
        except Exception:  # noqa: BLE001
            return None


def request_key(method: str, url: str, params: dict | None, body: object | None, headers: dict | None) -> str:
    safe_headers = {k.lower(): v for k, v in (headers or {}).items() if k.lower() not in SECRET_HEADERS}
    payload = json.dumps(
        {"m": method.upper(), "u": url, "p": params or {}, "b": body, "h": safe_headers},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class RawCache:
    """Disk cache: <dir>/<k[:2]>/<k>.bin + .json metadata. Same request -> cache hit."""

    def __init__(self, directory: Path, ttl_hours: float):
        self.dir = directory
        self.ttl_s = ttl_hours * 3600
        self.dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        d = self.dir / key[:2]
        return d / f"{key}.bin", d / f"{key}.json"

    def get(self, key: str) -> CachedResponse | None:
        body_p, meta_p = self._paths(key)
        if not (body_p.exists() and meta_p.exists()):
            return None
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if self.ttl_s > 0 and time.time() - meta.get("stored_at", 0) > self.ttl_s:
            return None
        return CachedResponse(meta["status_code"], body_p.read_bytes(), meta.get("headers", {}),
                              meta["url"], meta["retrieved_at"], True)

    def put(self, key: str, resp: CachedResponse) -> None:
        body_p, meta_p = self._paths(key)
        body_p.parent.mkdir(parents=True, exist_ok=True)
        body_p.write_bytes(resp.content)
        meta_p.write_text(json.dumps({
            "status_code": resp.status_code,
            "headers": {k.lower(): v for k, v in resp.headers.items()
                        if k.lower() in ("content-type", "content-disposition", "cmr-search-after", "cmr-hits")},
            "url": resp.url,
            "retrieved_at": resp.retrieved_at,
            "stored_at": time.time(),
        }))


class ResilientHTTP:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_s, connect=20.0),
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": "EarthTrendDetective/1.0 (NASA Space Apps 2026)"},
        )
        self.cache = RawCache(settings.cache_dir / "raw", settings.raw_cache_ttl_hours)
        self._buckets: dict[str, TokenBucket] = {}
        host_cdo = urlparse(settings.cdo_base).netloc + "/cdo-web"
        self._bucket_rules = {host_cdo: settings.cdo_rate_per_s}
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0, "throttled": 0}

    async def aclose(self) -> None:
        await self._client.aclose()

    def _bucket_for(self, url: str) -> TokenBucket | None:
        p = urlparse(url)
        for prefix, rate in self._bucket_rules.items():
            if (p.netloc + p.path).startswith(prefix):
                if prefix not in self._buckets:
                    self._buckets[prefix] = TokenBucket(rate)
                return self._buckets[prefix]
        return None

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: object | None = None,
        data: object | None = None,
        headers: dict | None = None,
        auth: tuple[str, str] | httpx.Auth | None = None,
        use_cache: bool = True,
        cache_statuses: tuple[int, ...] = (200,),
        expected: tuple[int, ...] = (200,),
    ) -> CachedResponse:
        key = request_key(method, url, params, json_body if json_body is not None else data, headers)
        if use_cache and not BYPASS_CACHE.get():
            hit = self.cache.get(key)
            if hit is not None:
                self.stats["cache_hits"] += 1
                return hit

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.s.http_max_retries:
            bucket = self._bucket_for(url)
            if bucket:
                await bucket.acquire()
            self.stats["requests"] += 1
            try:
                r = await self._client.request(method, url, params=params, json=json_body, data=data,
                                               headers=headers, auth=auth)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                wait = self._backoff(attempt, None)
                log.warning("transport error %s on %s; retry in %.1fs", exc, url, wait)
                attempt += 1
                self.stats["retries"] += 1
                await asyncio.sleep(wait)
                continue

            if r.status_code in RETRY_STATUS and attempt < self.s.http_max_retries:
                if r.status_code == 429:
                    self.stats["throttled"] += 1
                wait = self._backoff(attempt, _retry_after_seconds(r.headers.get("retry-after")))
                log.warning("HTTP %s from %s; retry %d in %.1fs", r.status_code, url, attempt + 1, wait)
                attempt += 1
                self.stats["retries"] += 1
                await asyncio.sleep(wait)
                continue

            resp = CachedResponse(r.status_code, r.content, {k.lower(): v for k, v in r.headers.items()}, str(r.url),
                                  datetime.now(timezone.utc).isoformat(timespec="seconds"), False)
            if r.status_code not in expected:
                snippet = r.text[:400] if r.content else ""
                raise UpstreamError(
                    f"{urlparse(url).netloc} returned HTTP {r.status_code}",
                    detail={"url": _redact(url), "status": r.status_code, "body": snippet},
                )
            if use_cache and r.status_code in cache_statuses:
                self.cache.put(key, resp)
            return resp

        raise UpstreamError(f"{urlparse(url).netloc} unreachable after {attempt} attempts",
                            detail={"url": _redact(url), "error": repr(last_exc)})

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.s.http_backoff_cap_s)
        # full jitter
        return random.uniform(0, min(self.s.http_backoff_cap_s, self.s.http_backoff_base_s * (2 ** attempt)))


def _redact(url: str) -> str:
    return url.split("?")[0] if "token=" in url.lower() else url
