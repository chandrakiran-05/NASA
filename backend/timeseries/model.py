"""Canonical series containers shared by connectors, the time-series engine and analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Provenance:
    source_api: str                       # e.g. "giovanni.timeseries", "appeears.point", "ncei.ads"
    variable: str                         # upstream variable / layer / datatype name
    geometry: dict
    dataset_short_name: str | None = None
    version: str | None = None
    concept_id: str | None = None
    product_id: str | None = None
    request_url: str | None = None        # never contains secrets
    retrieved_at: str = field(default_factory=utc_now_iso)
    doi: str | None = None
    citation: str | None = None
    notes: list[str] = field(default_factory=list)
    from_cache: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValueMeta:
    """Source metadata used for QC (architecture §4: mask using the source's own metadata)."""
    fill_values: tuple[float, ...] = ()
    scale_factor: float | None = None
    add_offset: float | None = None
    valid_min: float | None = None        # in RAW (unscaled) units when scale_factor given
    valid_max: float | None = None
    already_scaled: bool | None = None    # None = auto-detect
    units: str | None = None
    long_name: str | None = None


@dataclass
class RawSeries:
    time: np.ndarray                      # datetime64[ns], UTC, naive
    value: np.ndarray                     # float64
    native_resolution: str                # hourly | 3-hourly | daily | 8-day | 16-day | monthly
    provenance: Provenance
    meta: ValueMeta = field(default_factory=ValueMeta)
    qc_pass: np.ndarray | None = None     # bool mask from quality flags, if any
    period_days: np.ndarray | None = None # composite length (8-day / 16-day products), for weighting

    def __post_init__(self):
        self.time = np.asarray(self.time, dtype="datetime64[ns]")
        self.value = np.asarray(self.value, dtype="float64")
        order = np.argsort(self.time, kind="stable")
        if not np.all(order == np.arange(len(order))):
            self.time = self.time[order]
            self.value = self.value[order]
            if self.qc_pass is not None:
                self.qc_pass = np.asarray(self.qc_pass)[order]
            if self.period_days is not None:
                self.period_days = np.asarray(self.period_days)[order]

    def to_frame(self) -> pd.DataFrame:
        df = pd.DataFrame({"time": self.time, "value": self.value})
        if self.qc_pass is not None:
            df["qc_pass"] = self.qc_pass
        return df


@dataclass
class MonthlySeries:
    time: pd.DatetimeIndex                # regular month-start index (freq MS)
    value: np.ndarray                     # NaN where missing; never interpolated
    units: str | None
    provenance: Provenance
    n_obs: np.ndarray | None = None
    qc_pass_ratio: np.ndarray | None = None
    variable_id: str | None = None
    series_id: str | None = None
    label: str | None = None

    def __post_init__(self):
        self.value = np.asarray(self.value, dtype="float64")
        if not isinstance(self.time, pd.DatetimeIndex):
            self.time = pd.DatetimeIndex(self.time)

    @property
    def n(self) -> int:
        return len(self.value)

    @property
    def n_valid(self) -> int:
        return int(np.isfinite(self.value).sum())

    def t_years(self) -> np.ndarray:
        """Decimal years since series start, at mid-month spacing (1/12 yr per step)."""
        months = (self.time.year - self.time[0].year) * 12 + (self.time.month - self.time[0].month)
        return np.asarray(months, dtype="float64") / 12.0

    def completeness(self) -> dict:
        valid = np.isfinite(self.value)
        longest = cur = 0
        for v in valid:
            cur = 0 if v else cur + 1
            longest = max(longest, cur)
        return {
            "n_months": self.n,
            "n_valid": int(valid.sum()),
            "missing_pct": round(float(100.0 * (1 - valid.mean())), 2) if self.n else 100.0,
            "longest_gap_months": int(longest),
            "start": self.time[0].strftime("%Y-%m") if self.n else None,
            "end": self.time[-1].strftime("%Y-%m") if self.n else None,
        }

    def to_frame(self) -> pd.DataFrame:
        df = pd.DataFrame({"time": self.time, "value": self.value})
        if self.n_obs is not None:
            df["n_obs"] = self.n_obs
        if self.qc_pass_ratio is not None:
            df["qc_pass_ratio"] = self.qc_pass_ratio
        return df

    @classmethod
    def from_arrays(cls, times, values, units=None, provenance: Provenance | None = None, **kw) -> "MonthlySeries":
        """Build a regular monthly series from (time, value) pairs; duplicates averaged, gaps -> NaN."""
        t = pd.to_datetime(pd.Series(times), utc=True).dt.tz_convert(None)
        df = pd.DataFrame({"t": t.dt.to_period("M").dt.to_timestamp(), "v": np.asarray(values, dtype=float)})
        g = df.groupby("t")["v"].mean()
        idx = pd.date_range(g.index.min(), g.index.max(), freq="MS")
        g = g.reindex(idx)
        prov = provenance or Provenance(source_api="user", variable="value", geometry={})
        return cls(time=idx, value=g.to_numpy(), units=units, provenance=prov, **kw)
