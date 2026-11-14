"""Gridded netCDF helpers (AppEEARS area tasks, Harmony subsets, Cloud OPeNDAP granules).

* `area_mean`   cos(latitude)-weighted mean of valid pixels inside the region, per time step
* `to_cube`     (time, lat, lon) array for per-pixel trend maps
xarray decodes CF scale_factor/add_offset/_FillValue automatically (mask_and_scale=True), so
the source's own metadata drives the masking.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from ..core.geometry import Region, point_in_polygon

LAT_NAMES = ("lat", "latitude", "y", "Latitude")
LON_NAMES = ("lon", "longitude", "x", "Longitude")
TIME_NAMES = ("time", "Time", "date")


def _coord(ds, names):
    for n in names:
        if n in ds.coords or n in ds.dims or n in ds.variables:
            return n
    raise KeyError(f"none of {names} found in dataset")


def open_many(paths: list[Path | str]) -> xr.Dataset:
    dss = [xr.open_dataset(p, engine="h5netcdf", mask_and_scale=True, decode_times=True) for p in paths]
    if len(dss) == 1:
        return dss[0]
    tname = _coord(dss[0], TIME_NAMES)
    return xr.concat(dss, dim=tname, data_vars="minimal", coords="minimal", compat="override").sortby(tname)


def find_variable(ds: xr.Dataset, name: str) -> str:
    if name in ds.data_vars:
        return name
    for v in ds.data_vars:
        if v.endswith(name) or name.endswith(v) or v.lower() == name.lower():
            return v
    raise KeyError(f"variable {name!r} not in dataset (have {list(ds.data_vars)[:20]})")


def _region_mask(lat: np.ndarray, lon: np.ndarray, region: Region | None) -> np.ndarray:
    LON, LAT = np.meshgrid(lon, lat)
    if region is None:
        return np.ones(LAT.shape, bool)
    w, s, e, n = region.bbox
    mask = (LON >= w) & (LON <= e) & (LAT >= s) & (LAT <= n)
    if region.kind == "polygon" and region.polygon:
        poly = region.polygon
        idx = np.argwhere(mask)
        for i, j in idx:
            if not point_in_polygon(LON[i, j], LAT[i, j], poly):
                mask[i, j] = False
    return mask


def valid_range_only(da: xr.DataArray, meta) -> xr.DataArray:
    """xarray masks only _FillValue; values outside the source's valid range (e.g. MODIS land-cover codes
    32761-32766 for water/urban above valid_max 32700) must not enter a mean. meta range is in raw units."""
    if meta.valid_min is None or meta.valid_max is None:
        return da
    sf, off = meta.scale_factor or 1.0, meta.add_offset or 0.0
    lo, hi = sorted((meta.valid_min * sf + off, meta.valid_max * sf + off))
    return da.where((da >= lo) & (da <= hi))


def area_mean(ds: xr.Dataset, var: str, region: Region | None = None, qc_good: np.ndarray | None = None,
              min_pixel_fraction: float = 0.3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (times, mean values, fraction of region pixels valid) per time step.

    A time step is NaN when fewer than `min_pixel_fraction` of the region's pixels are valid
    (cloud/snow masked composites would otherwise give unrepresentative means).
    """
    v = find_variable(ds, var)
    tname = _coord(ds, TIME_NAMES)
    latn, lonn = _coord(ds, LAT_NAMES), _coord(ds, LON_NAMES)
    da = ds[v].transpose(tname, latn, lonn)
    lat = ds[latn].values
    lon = ds[lonn].values
    arr = da.values.astype(np.float64)
    if qc_good is not None:
        arr = np.where(qc_good, arr, np.nan)
    mask = _region_mask(lat, lon, region)
    w = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, len(lon)))
    w = np.where(mask, w, 0.0)
    valid = np.isfinite(arr)
    total = w[valid.any(axis=0)].sum()      # pixels that never have data (sea in a land product) do not count
    wv = np.where(valid, w[None], 0.0)
    num = np.nansum(np.where(valid, arr, 0.0) * wv, axis=(1, 2))
    den = wv.sum(axis=(1, 2))
    frac = den / total if total > 0 else np.zeros_like(den)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where((den > 0) & (frac >= min_pixel_fraction), num / den, np.nan)
    return ds[tname].values.astype("datetime64[ns]"), mean, frac


def to_cube(ds: xr.Dataset, var: str, region: Region | None = None):
    v = find_variable(ds, var)
    tname = _coord(ds, TIME_NAMES)
    latn, lonn = _coord(ds, LAT_NAMES), _coord(ds, LON_NAMES)
    da = ds[v].transpose(tname, latn, lonn)
    lat = ds[latn].values
    lon = ds[lonn].values
    arr = da.values.astype(np.float64)
    mask = _region_mask(lat, lon, region)
    arr[:, ~mask] = np.nan
    times = ds[tname].values.astype("datetime64[ns]")
    return times, arr, lat, lon
