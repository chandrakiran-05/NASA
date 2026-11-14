"""Quality control: scale/offset, fill values, valid range, quality flags (architecture §4 C-D).

Everything uses the SOURCE's own metadata (FillValue, ScaleFactor, ValidMin/Max from
AppEEARS /product/{id}, CF attributes from netCDF, header fields from Giovanni).
Whether AppEEARS CSV values arrive pre-scaled is UNVERIFIED in our reference doc, so it is
auto-detected from the valid range and recorded in the QC report.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .model import RawSeries


def _detect_scaled(v: np.ndarray, vmin, vmax, scale, offset) -> bool | None:
    if scale is None or vmin is None or vmax is None:
        return None
    f = v[np.isfinite(v)]
    if not len(f):
        return None
    off = offset or 0.0
    lo_s, hi_s = sorted((vmin * scale + off, vmax * scale + off))
    in_scaled = np.mean((f >= lo_s) & (f <= hi_s))
    in_raw = np.mean((f >= vmin) & (f <= vmax))
    if in_scaled == in_raw:  # ambiguous (e.g. all zeros) -> trust the magnitude
        return bool(np.nanmax(np.abs(f)) <= max(abs(lo_s), abs(hi_s)) * 1.0001)
    return bool(in_scaled > in_raw)


def apply_qc(raw: RawSeries) -> tuple[RawSeries, dict]:
    v = raw.value.copy()
    m = raw.meta
    n_total = int(len(v))
    report = {"n_total": n_total}

    # 1. fill values (compare in both raw and scaled space; harmless if one never matches)
    fill_mask = np.zeros(n_total, bool)
    for fv in m.fill_values:
        if fv is None:
            continue
        fill_mask |= np.isclose(v, fv)
        if m.scale_factor:
            fill_mask |= np.isclose(v, fv * m.scale_factor + (m.add_offset or 0.0))
    v[fill_mask] = np.nan
    report["n_fill"] = int(fill_mask.sum())

    # 2. scale / offset
    scaled = m.already_scaled
    if scaled is None:
        scaled = _detect_scaled(v, m.valid_min, m.valid_max, m.scale_factor, m.add_offset)
        report["scaling_autodetected"] = scaled
    if m.scale_factor and not scaled:
        v = v * m.scale_factor + (m.add_offset or 0.0)
        report["scale_applied"] = {"scale_factor": m.scale_factor, "add_offset": m.add_offset or 0.0}

    # 3. valid range (raw-unit limits converted to scaled units when a scale exists)
    oor = np.zeros(n_total, bool)
    if m.valid_min is not None or m.valid_max is not None:
        sc = m.scale_factor or 1.0
        off = (m.add_offset or 0.0) if m.scale_factor else 0.0
        lo = m.valid_min * sc + off if m.valid_min is not None else -np.inf
        hi = m.valid_max * sc + off if m.valid_max is not None else np.inf
        lo, hi = min(lo, hi), max(lo, hi)
        with np.errstate(invalid="ignore"):
            oor = np.isfinite(v) & ((v < lo) | (v > hi))
        v[oor] = np.nan
    report["n_out_of_range"] = int(oor.sum())

    # 4. quality flags
    bad = np.zeros(n_total, bool)
    if raw.qc_pass is not None:
        bad = np.isfinite(v) & ~np.asarray(raw.qc_pass, bool)
        v[bad] = np.nan
    report["n_bad_quality_flag"] = int(bad.sum())
    report["n_valid"] = int(np.isfinite(v).sum())
    return replace(raw, value=v, meta=replace(m, already_scaled=True)), report


def convert_units(raw: RawSeries, factor: float = 1.0, offset: float = 0.0, units: str | None = None) -> RawSeries:
    if factor == 1.0 and offset == 0.0:
        return raw
    return replace(raw, value=raw.value * factor + offset, meta=replace(raw.meta, units=units or raw.meta.units))
