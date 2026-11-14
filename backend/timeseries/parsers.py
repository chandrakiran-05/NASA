"""Parsers for each upstream response format (02-platforms-and-apis.md).

All parsers are tolerant of small layout changes: they look for the data header by name
instead of assuming a fixed line count, and they never guess values.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re

import numpy as np
import pandas as pd

from ..core.errors import UpstreamError

_MISSING_TOKENS = {"", "nan", "na", "n/a", "null", "none", "-", "--"}


def _to_float(s) -> float:
    if s is None:
        return math.nan
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if s.lower() in _MISSING_TOKENS:
        return math.nan
    try:
        return float(s)
    except ValueError:
        return math.nan


def _to_time(values) -> np.ndarray:
    t = pd.to_datetime(pd.Series(values), utc=True, errors="coerce").dt.tz_convert(None)
    return t.to_numpy(dtype="datetime64[ns]")


# --------------------------------------------------------------------------------------
# Giovanni in the Cloud  /timeseries   (point)
# Verified against NASA's own tutorial (nasa/gesdisc-tutorials,
# How_to_Access_GiC_Time_Series_Service.ipynb): "the first 13 rows are header" of the form
# key,value (param_name = long variable name, unit, lat, lon, ...), followed by a column-header
# row and Timestamp,value data rows. We read the key,value block, then take every later row whose
# first cell parses as a timestamp, so an extra blank/"," line or a renamed header cannot break it.
# --------------------------------------------------------------------------------------
GIOVANNI_HEADER_LINES = 13


def _looks_like_time(cell: str) -> bool:
    return bool(re.match(r"^\s*\d{4}-\d{2}-\d{2}", cell or ""))


def parse_giovanni_timeseries_csv(text: str) -> tuple[dict, np.ndarray, np.ndarray]:
    lines = text.splitlines()
    header: dict[str, str] = {}
    i = 0
    while i < len(lines) and i < GIOVANNI_HEADER_LINES + 2:
        line = lines[i]
        cells = next(csv.reader([line])) if line.strip() else []
        if cells and _looks_like_time(cells[0]):
            break
        if len(cells) >= 2 and cells[0].strip() and not cells[0].strip().lower().startswith("timestamp"):
            header[cells[0].strip()] = ",".join(c.strip() for c in cells[1:]).strip()
        elif cells and cells[0].strip().lower().startswith("timestamp"):
            header["_columns"] = ",".join(c.strip() for c in cells)
        i += 1
    times, vals = [], []
    for line in lines[i:]:
        if not line.strip():
            continue
        cells = next(csv.reader([line]))
        if len(cells) < 2 or not _looks_like_time(cells[0]):
            continue
        times.append(cells[0].strip())
        vals.append(_to_float(cells[1]))
    if not times:
        hint = ("The returned CSV is empty: check the location is inside the dataset's extent (land-only "
                "variables are masked over ocean) and that the Earthdata token is valid.")
        raise UpstreamError("Giovanni returned no time-series rows", detail={"head": text[:300], "hint": hint})
    fill = None
    for k in ("fill_value", "_FillValue", "missing_value", "fillvalue"):
        if k in header:
            fill = _to_float(header[k])
    v = np.asarray(vals, float)
    if fill is not None and math.isfinite(fill):
        v[np.isclose(v, fill)] = np.nan
    return header, _to_time(times), v


# --------------------------------------------------------------------------------------
# Harmony area-average CSV:   header block ... a line that is only ",",  then time,mean_<var>
# --------------------------------------------------------------------------------------
def parse_harmony_area_csv(text: str) -> tuple[dict, np.ndarray, np.ndarray]:
    lines = text.splitlines()
    header: dict[str, str] = {}
    start = None
    for i, line in enumerate(lines):
        if line.strip() == ",":
            start = i + 1
            break
        cells = next(csv.reader([line])) if line.strip() else []
        if len(cells) >= 2:
            header[cells[0].strip()] = ",".join(c.strip() for c in cells[1:]).strip()
    if start is None:  # tolerate a file with no metadata block
        start = next((i for i, l in enumerate(lines) if l.lower().startswith("time,")), None)
        if start is None:
            raise UpstreamError("Harmony CSV: could not find the data block", detail={"head": text[:300]})
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    tcol = next((c for c in df.columns if c.strip().lower() in ("time", "timestamp", "date")), df.columns[0])
    vcol = next((c for c in df.columns if c.strip().lower().startswith("mean")), df.columns[-1])
    header["_value_column"] = vcol
    return header, _to_time(df[tcol]), pd.to_numeric(df[vcol], errors="coerce").to_numpy(float)


# --------------------------------------------------------------------------------------
# AppEEARS point-sample CSV: one row per date; value column "<PRODUCT>_<VER>_<LAYER>"
# --------------------------------------------------------------------------------------
def appeears_column_name(product_id: str, layer: str) -> str:
    return f"{product_id.replace('.', '_')}_{layer}"


def parse_appeears_point_csv(text: str, product_id: str, layer: str, point_id: str | None = None,
                             qc_column: str | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    df = pd.read_csv(io.StringIO(text))
    col = appeears_column_name(product_id, layer)
    if col not in df.columns:
        cands = [c for c in df.columns if c.endswith(layer)]
        if not cands:
            raise UpstreamError(f"AppEEARS CSV has no column for layer {layer}",
                                detail={"columns": list(df.columns)[:40]})
        col = cands[0]
    if point_id is not None and "ID" in df.columns:
        df = df[df["ID"].astype(str) == str(point_id)]
    date_col = "Date" if "Date" in df.columns else next(c for c in df.columns if "date" in c.lower())
    qc = None
    if qc_column and qc_column in df.columns:
        qc = df[qc_column].to_numpy()
    return _to_time(df[date_col]), pd.to_numeric(df[col], errors="coerce").to_numpy(float), qc


# --------------------------------------------------------------------------------------
# NCEI Access Data Service JSON: [{"DATE": "2000-01", "STATION": "...", "TAVG": " 1.2", ...}]
# --------------------------------------------------------------------------------------
def parse_ncei_ads_json(payload: str | list, datatype: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rows = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    if not isinstance(rows, list):
        raise UpstreamError("NCEI ADS: expected a JSON list", detail={"type": type(rows).__name__})
    times, vals, stations = [], [], []
    for r in rows:
        if datatype not in r:
            continue
        d = str(r.get("DATE", ""))
        if re.fullmatch(r"\d{4}-\d{2}", d):
            d = d + "-01"
        times.append(d)
        vals.append(_to_float(r.get(datatype)))
        stations.append(str(r.get("STATION", "")))
    return _to_time(times), np.asarray(vals, float), stations


# --------------------------------------------------------------------------------------
# NOAA CDO v2 /data JSON: {"metadata": {...}, "results": [{"date", "datatype", "value", ...}]}
# --------------------------------------------------------------------------------------
def parse_cdo_json(payloads: list[dict], datatype: str) -> tuple[np.ndarray, np.ndarray]:
    times, vals = [], []
    for p in payloads:
        for r in p.get("results", []) or []:
            if r.get("datatype") != datatype:
                continue
            times.append(r.get("date"))
            vals.append(_to_float(r.get("value")))
    return _to_time(times), np.asarray(vals, float)


# --------------------------------------------------------------------------------------
# Giovanni configured-variables listing (format tolerant)
# --------------------------------------------------------------------------------------
_GID = re.compile(r"^(?P<short>.+?)_(?P<ver>\d+(?:_\d+)*|R\d{4}|\d+r)_(?P<var>.+)$")


def split_giovanni_id(gid: str) -> dict:
    """'GLDAS_NOAH025_3H_2_1_Tair_f_inst' -> short GLDAS_NOAH025_3H, version 2.1, var Tair_f_inst.

    Best effort: the ID itself is treated as opaque by the connector.
    """
    m = _GID.match(gid)
    if not m:
        return {"id": gid, "short_name": None, "version": None, "variable": None}
    return {"id": gid, "short_name": m["short"], "version": m["ver"].replace("_", "."), "variable": m["var"]}


def parse_configured_variables(payload) -> list[str]:
    data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    ids: list[str] = []

    def walk(x):
        if isinstance(x, str):
            ids.append(x)
        elif isinstance(x, list):
            for e in x:
                walk(e)
        elif isinstance(x, dict):
            for k in ("id", "variable_id", "name", "dataId", "data_id"):
                if isinstance(x.get(k), str):
                    ids.append(x[k])
                    return
            for k in ("variables", "configured_variables", "items", "data", "results"):
                if k in x:
                    walk(x[k])
                    return
            # dict keyed by id
            if all(isinstance(k, str) for k in x.keys()) and len(x) > 3:
                ids.extend(x.keys())

    walk(data)
    # keep every well-formed ID: real IDs include non-numeric versions (NOBM_DAY_R2017_chl, OCO2_..._10r_XCO2)
    return sorted({i for i in ids if re.fullmatch(r"[A-Za-z0-9_]+", i) and "_" in i})
