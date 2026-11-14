"""Parquet persistence for normalized monthly series (architecture ⑦ K2)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..core.errors import NotFound
from ..timeseries.model import MonthlySeries, Provenance
from .db import Database


def make_series_id(request_hash: str) -> str:
    return "s_" + request_hash[:16]


def hash_request(variable_id: str, region_key: str, start: str, end: str, extra: dict | None = None) -> str:
    payload = json.dumps({"v": variable_id, "r": region_key, "s": start, "e": end, "x": extra or {}}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class SeriesStore:
    def __init__(self, directory: Path, db: Database):
        self.dir = directory
        self.db = db
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, series_id: str) -> Path:
        return self.dir / f"{series_id}.parquet"

    def save(self, ms: MonthlySeries, *, series_id: str, request_hash: str | None, region: dict | None) -> str:
        df = ms.to_frame()
        table = pa.Table.from_pandas(df, preserve_index=False)
        meta = {
            b"units": (ms.units or "").encode(),
            b"variable_id": (ms.variable_id or "").encode(),
            b"label": (ms.label or "").encode(),
            b"provenance": json.dumps(ms.provenance.to_dict(), default=str).encode(),
        }
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), **meta})
        pq.write_table(table, self._path(series_id), compression="zstd")
        self.db.delete_results(series_id)       # analyses of the old data are stale
        ms.series_id = series_id
        comp = ms.completeness()
        self.db.upsert_series({
            "series_id": series_id,
            "request_hash": request_hash,
            "variable_id": ms.variable_id,
            "label": ms.label,
            "region": region,
            "units": ms.units,
            "start": comp["start"],
            "end": comp["end"],
            "source_api": ms.provenance.source_api,
            "provenance": ms.provenance.to_dict(),
            "completeness": comp,
        })
        return series_id

    def load(self, series_id: str) -> MonthlySeries:
        p = self._path(series_id)
        if not p.exists():
            raise NotFound(f"Series {series_id} not found")
        table = pq.read_table(p)
        md = table.schema.metadata or {}
        df = table.to_pandas()
        prov_d = json.loads(md.get(b"provenance", b"{}") or b"{}")
        prov = Provenance(**prov_d) if prov_d else Provenance(source_api="unknown", variable="value", geometry={})
        ms = MonthlySeries(
            time=pd.DatetimeIndex(df["time"]),
            value=df["value"].to_numpy(dtype=float),
            units=(md.get(b"units", b"").decode() or None),
            provenance=prov,
            n_obs=df["n_obs"].to_numpy() if "n_obs" in df else None,
            qc_pass_ratio=df["qc_pass_ratio"].to_numpy() if "qc_pass_ratio" in df else None,
            variable_id=(md.get(b"variable_id", b"").decode() or None),
            label=(md.get(b"label", b"").decode() or None),
            series_id=series_id,
        )
        return ms

    def exists(self, series_id: str) -> bool:
        return self._path(series_id).exists()


def frame_to_records(time: pd.DatetimeIndex, value: np.ndarray, decimals: int = 6) -> dict:
    vals = [None if not np.isfinite(v) else round(float(v), decimals) for v in value]
    return {"time": [t.strftime("%Y-%m-%d") for t in time], "value": vals}
