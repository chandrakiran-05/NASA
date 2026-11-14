"""Native resolution -> regular monthly series with a completeness rule (architecture §4 E-I).

* hourly / 3-hourly : -> daily mean (day kept if >= threshold of its expected samples)
                       -> monthly mean (month kept if >= threshold of its days are valid)
* daily             : -> monthly mean (same day-coverage rule)
* 8-day / 16-day    : composites expanded to the days they represent (clipped at year end,
                       MODIS convention) -> day-weighted monthly mean
* monthly           : used as-is
Gaps stay NaN; nothing is interpolated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .model import MonthlySeries, RawSeries

SAMPLES_PER_DAY = {"hourly": 24, "3-hourly": 8, "6-hourly": 4}
COMPOSITE_DAYS = {"8-day": 8, "16-day": 16}


def _month_index(start, end) -> pd.DatetimeIndex:
    s = pd.Timestamp(start).to_period("M").to_timestamp()
    e = pd.Timestamp(end).to_period("M").to_timestamp()
    return pd.date_range(s, e, freq="MS")


def _daily_to_monthly(day_vals: pd.Series, idx: pd.DatetimeIndex, thr: float):
    by_month = day_vals.groupby(day_vals.index.to_period("M"))
    mean = by_month.mean()
    cnt = by_month.count()
    out = np.full(len(idx), np.nan)
    nobs = np.zeros(len(idx), dtype=int)
    ratio = np.zeros(len(idx))
    pos = {p.to_timestamp(): i for i, p in enumerate(idx.to_period("M"))}
    for per, v in mean.items():
        ts = per.to_timestamp()
        if ts not in pos:
            continue
        i = pos[ts]
        days = per.days_in_month
        c = int(cnt[per])
        nobs[i] = c
        ratio[i] = c / days
        if c / days >= thr:
            out[i] = v
    return out, nobs, ratio


def to_monthly(raw: RawSeries, *, start=None, end=None, min_valid_fraction: float = 0.7,
               variable_id: str | None = None, label: str | None = None) -> MonthlySeries:
    t = pd.DatetimeIndex(raw.time)
    v = pd.Series(raw.value, index=t)
    if start is None:
        start = t.min()
    if end is None:
        end = t.max()
    idx = _month_index(start, end)
    res = raw.native_resolution
    thr = min_valid_fraction

    if res == "monthly":
        s = v.groupby(t.to_period("M")).mean()
        out = np.full(len(idx), np.nan)
        nobs = np.zeros(len(idx), dtype=int)
        pos = {p: i for i, p in enumerate(idx.to_period("M"))}
        for per, val in s.items():
            if per in pos:
                out[pos[per]] = val
                nobs[pos[per]] = int(np.isfinite(val))
        ratio = nobs.astype(float)
    elif res in SAMPLES_PER_DAY:
        per_day = SAMPLES_PER_DAY[res]
        g = v.groupby(t.normalize())
        dmean, dcnt = g.mean(), g.count()
        daily = dmean.where(dcnt >= np.ceil(thr * per_day))
        out, nobs, ratio = _daily_to_monthly(daily.dropna(), idx, thr)
    elif res == "daily":
        daily = v.groupby(t.normalize()).mean().dropna()
        out, nobs, ratio = _daily_to_monthly(daily, idx, thr)
    elif res in COMPOSITE_DAYS:
        span = COMPOSITE_DAYS[res]
        rows_t, rows_v = [], []
        periods = raw.period_days
        for k, (ts, val) in enumerate(zip(t, raw.value)):
            if not np.isfinite(val):
                continue
            n_days = int(periods[k]) if periods is not None else span
            year_end = pd.Timestamp(year=ts.year, month=12, day=31)
            days = pd.date_range(ts.normalize(), min(ts.normalize() + pd.Timedelta(days=n_days - 1), year_end))
            rows_t.append(days)
            rows_v.append(np.full(len(days), val))
        if rows_t:
            daily = pd.Series(np.concatenate(rows_v), index=pd.DatetimeIndex(np.concatenate([d.values for d in rows_t])))
            daily = daily.groupby(level=0).mean()
        else:
            daily = pd.Series(dtype=float)
        out, nobs, ratio = _daily_to_monthly(daily, idx, thr)
    else:
        raise ValueError(f"unsupported native resolution {res!r}")

    return MonthlySeries(time=idx, value=out, units=raw.meta.units, provenance=raw.provenance,
                         n_obs=nobs, qc_pass_ratio=ratio, variable_id=variable_id, label=label)
