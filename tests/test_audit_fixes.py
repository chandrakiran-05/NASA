"""Regression tests for bugs found in the 2026-11-14 audit."""
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from backend.timeseries.model import MonthlySeries, Provenance
from tests.conftest import wait_job

CHENNAI = {"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"}


def test_refresh_redownloads_and_drops_stale_analyses(client):
    body = {"variable_id": "merra2_t2m", "geometry": CHENNAI, "start": "2001-01", "end": "2020-12"}
    sid = wait_job(client, client.post("/api/timeseries", json=body).json()["job_id"])["result"]["series_id"]
    client.post("/api/analyze", json={"series_id": sid})
    st = client.app.state.etd
    assert st.db._conn.execute("SELECT COUNT(*) FROM results WHERE series_id=?", (sid,)).fetchone()[0] > 0
    n_calls = len(client.fake.calls)
    j = wait_job(client, client.post("/api/timeseries", json={**body, "refresh": True}).json()["job_id"])
    assert j["status"] == "done" and not j["result"]["cached"]
    assert len(client.fake.calls) > n_calls                       # went upstream, not to the raw cache
    assert st.db._conn.execute("SELECT COUNT(*) FROM results WHERE series_id=?", (sid,)).fetchone()[0] == 0


def test_bad_uploads_give_json_errors_not_bare_500(client):
    r = client.post("/api/timeseries/upload-csv",
                    files={"file": ("a.csv", "date,value\n2001-01,1\n2001-02,2,3,4\n", "text/csv")})
    assert r.status_code == 422 and "CSV" in r.json()["error"]["message"]
    r = client.post("/api/timeseries/upload", json={"time": ["2001-01", "not a date"], "value": [1, 2]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


def test_parallel_beast_restores_the_global_hook():
    from backend.insights.onset import change_onset
    n = 240
    t = np.arange(n) / 12
    idx = pd.date_range("2000-01-01", periods=n, freq="MS")
    rng = np.random.default_rng(0)
    series = [MonthlySeries(time=idx, value=0.05 * t + rng.normal(0, .5, n), units="C",
                            provenance=Provenance(source_api="u", variable="v", geometry={})) for _ in range(6)]
    hook = sys.unraisablehook
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda s: change_onset(s, n_surrogates=19), series))
    assert sys.unraisablehook is hook


def test_finished_active_job_is_not_reused(client):
    vals = (0.05 * np.arange(300) / 12).tolist()
    idx = pd.date_range("2000-01-01", periods=300, freq="MS")
    sid = client.post("/api/timeseries/upload", json={"time": [str(d.date()) for d in idx], "value": vals}).json()["series_id"]
    body = {"series_ids": [sid], "ai_review": False}
    first = client.post("/api/active-trends", json=body).json()["job_id"]
    assert wait_job(client, first, timeout=120)["status"] == "done"
    assert client.post("/api/active-trends", json=body).json()["job_id"] != first


def test_area_mean_drops_land_cover_codes_and_ignores_sea_pixels():
    import io
    import xarray as xr
    from backend.core.geometry import parse_geometry
    from backend.timeseries.gridded import area_mean, valid_range_only
    from backend.timeseries.model import ValueMeta
    raw = np.array([[[150, 32766], [200, 180]]], "int16")            # 32766 = MODIS "water" code
    ds = xr.Dataset({"ET_500m": (("time", "lat", "lon"), raw, {"_FillValue": np.int16(32767), "scale_factor": 0.1})},
                    coords={"time": [np.datetime64("2001-01-01")], "lat": [13.0, 13.01], "lon": [80.0, 80.01]})
    buf = io.BytesIO()
    ds.to_netcdf(buf, engine="h5netcdf")
    buf.seek(0)
    d = xr.open_dataset(buf, engine="h5netcdf", mask_and_scale=True)
    d["ET_500m"] = valid_range_only(d["ET_500m"], ValueMeta(scale_factor=0.1, valid_min=-32767, valid_max=32700))
    box = parse_geometry({"type": "BBox", "bbox": [79.9, 12.9, 80.1, 13.1]})
    _, mean, frac = area_mean(d, "ET_500m", box)
    assert abs(mean[0] - np.mean([15.0, 20.0, 18.0])) < 0.01
    # a pixel that is never valid (sea) does not count against the valid-pixel fraction
    assert frac[0] == 1.0


def test_station_average_keeps_a_trend_across_non_overlapping_stations():
    from backend.connectors.ncei import anomaly_average
    idx = pd.date_range("1990-01-01", "2019-12-01", freq="MS")
    yrs = (idx.year - 1990) + (idx.month - 1) / 12
    truth = 25 + 0.03 * yrs
    full = pd.Series(truth, index=idx)
    early = pd.Series(np.where(idx.year < 2004, truth + 1.0, np.nan), index=idx)
    late = pd.Series(np.where(idx.year >= 2005, truth - 0.5, np.nan), index=idx)
    out = anomaly_average({"F": full, "E": early, "L": late})
    assert abs(np.polyfit(yrs, out.to_numpy(), 1)[0] * 10 - 0.30) < 0.02


def test_geometry_and_empty_composite_edge_cases():
    import pytest
    from backend.core.errors import InvalidRequest
    from backend.core.geometry import parse_geometry
    from backend.timeseries.model import RawSeries, ValueMeta
    from backend.timeseries.resample import to_monthly
    with pytest.raises(InvalidRequest):
        parse_geometry({"type": "Polygon", "coordinates": [[[178, -20], [-178, -20], [-178, -16], [178, -16], [178, -20]]]})
    t = pd.date_range("2001-01-01", periods=10, freq="8D").to_numpy("datetime64[ns]")
    raw = RawSeries(t, np.full(10, np.nan), "8-day", Provenance(source_api="u", variable="v", geometry={}), ValueMeta())
    ms = to_monthly(raw, start=pd.Timestamp("2001-01-01").date(), end=pd.Timestamp("2001-03-31").date(),
                    min_valid_fraction=0.7)
    assert ms.n_valid == 0
