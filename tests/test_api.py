"""End-to-end API tests: every endpoint, through FastAPI, against the fake upstream."""
import io

import numpy as np
import pandas as pd

from tests.conftest import wait_job

CHENNAI = {"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"}


def make_series(client, variable="imerg_precip_monthly", geom=CHENNAI, start="2001-01", end="2020-12"):
    r = client.post("/api/timeseries", json={"variable_id": variable, "geometry": geom, "start": start, "end": end})
    assert r.status_code == 202, r.text
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done", j
    return j["result"]["series_id"]


def test_health_variables_detail_regions(client):
    assert client.get("/api/health").json()["status"] == "ok"
    v = client.get("/api/variables", params={"q": "rainfall"}).json()["variables"]
    assert v[0]["id"].startswith("imerg_precip")
    d = client.get("/api/variables/merra2_t2m").json()
    assert d["dataset"]["concept_id"] == "C1276812863-GES_DISC" and d["cmr_link"].startswith("https://cmr")
    assert client.get("/api/variables/nope").status_code == 404
    arch = client.get("/api/variables", params={"region_type": "desert"}).json()["variables"]
    assert arch[0]["id"] == "modis_lst_day"
    r = client.get("/api/regions/search", params={"q": "Kerala"}).json()["results"]
    assert r[0]["name"] == "Kerala" and r[0]["approximate"]


def test_timeseries_validation_errors(client):
    bad = client.post("/api/timeseries", json={"variable_id": "merra2_t2m", "geometry": CHENNAI,
                                               "start": "2020-01", "end": "2020-06"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    bad = client.post("/api/timeseries", json={"variable_id": "merra2_t2m",
                                               "geometry": {"type": "Point", "coordinates": [200, 0]},
                                               "start": "2001", "end": "2010"})
    assert bad.status_code == 422


def test_full_flow_series_views_analyze_insights_export(client):
    sid = make_series(client)
    for view in ("monthly", "deseasonalized", "anomaly", "annual", "raw"):
        r = client.get(f"/api/timeseries/{sid}", params={"view": view})
        assert r.status_code == 200, (view, r.text)
        assert len(r.json()["time"]) == len(r.json()["value"])
    a = client.post("/api/analyze", json={"series_id": sid}).json()
    assert a["units"] == "mm/day"
    assert a["mann_kendall"]["variant"] == "ess_ar1"
    assert {"ols", "mann_kendall", "seasonal_mk", "sen", "diagnostics", "verdict", "provenance", "chart"} <= set(a)
    assert a["provenance"]["source_api"] == "giovanni.timeseries"
    assert "plain_language" in a["verdict"]
    ins = client.post("/api/insights", json={"series_id": sid, "forecast_horizon": 24}).json()
    assert 0 <= ins["trend_evidence_index"]["score"] <= 100
    assert len(ins["forecast"]["forecast"]["mean"]) == 24
    csv = client.get(f"/api/export/{sid}").text
    assert csv.startswith("# ") and "citation" in csv and "time,value" in csv
    js = client.get(f"/api/export/{sid}", params={"format": "json"}).json()
    assert js["citation"] and len(js["time"]) == 240
    assert client.get("/api/series").json()["series"][0]["series_id"] == sid


def test_compare_and_drivers(client):
    a = make_series(client, geom={"type": "BBox", "bbox": [76.0, 9.0, 77.0, 10.0], "name": "A"})
    b = make_series(client, geom={"type": "BBox", "bbox": [72.0, 25.0, 73.0, 26.0], "name": "B"})
    c = client.post("/api/compare", json={"series_ids": [a, b]}).json()
    assert len(c["regions"]) == 2 and c["correction"] == "Benjamini-Hochberg FDR"
    t2m = make_series(client, variable="merra2_t2m", start="2001-01", end="2004-12")
    d = client.post("/api/drivers", json={"target_series_id": a, "driver_series_ids": [t2m]})
    assert d.status_code == 200 and "drivers" in d.json()


def test_upload_json_and_csv_and_trendmap_upload(client, tmp_path):
    idx = pd.date_range("1990-01-01", periods=240, freq="MS")
    rng = np.random.default_rng(0)
    vals = (10 + 3 * np.sin(2 * np.pi * idx.month.to_numpy() / 12) + 0.05 * np.arange(240) / 12
            + rng.normal(0, 0.3, 240)).round(3).tolist()
    r = client.post("/api/timeseries/upload", json={"time": [str(t.date()) for t in idx], "value": vals,
                                                     "units": "degC", "label": "KNMI export"})
    sid = r.json()["series_id"]
    assert client.post("/api/analyze", json={"series_id": sid}).json()["verdict"]["direction"] == "rising"
    csv = "# exported from somewhere\ntime,value\n" + "\n".join(f"{t.date()},{v}" for t, v in zip(idx, vals))
    r = client.post("/api/timeseries/upload-csv", files={"file": ("x.csv", csv, "text/csv")}, data={"units": "degC"})
    assert r.status_code == 200, r.text
    import xarray as xr
    lat, lon = np.linspace(10, 12, 5), np.linspace(78, 80, 6)
    cube = rng.normal(0, 1, (240, 5, 6)) + (np.arange(240) / 12)[:, None, None] * 0.1
    buf = io.BytesIO()
    xr.Dataset({"T2M": (("time", "lat", "lon"), cube)}, coords={"time": idx, "lat": lat, "lon": lon}).to_netcdf(
        buf, engine="h5netcdf")
    r = client.post("/api/trendmap/upload", files={"file": ("c.nc", buf.getvalue(), "application/x-netcdf")},
                    data={"variable": "T2M"})
    assert r.status_code == 200, r.text
    assert r.json()["area_fraction_rising"] > 0.9


def test_trendmap_job_via_opendap(client):
    r = client.post("/api/trendmap", json={"variable_id": "merra2_t2m", "start": "2001-01", "end": "2010-12",
                                           "geometry": {"type": "BBox", "bbox": [76.0, 10.0, 80.0, 12.0]}})
    j = wait_job(client, r.json()["job_id"], 60)
    assert j["status"] == "done", j
    res = j["result"]
    assert len(res["lat"]) > 1 and len(res["lon"]) > 1
    assert res["area_fraction_rising"] > 0.2 and res["area_fraction_falling"] > 0.2   # planted opposite trends


def test_investigate_question_end_to_end(client):
    client.fake.llm_reply = None          # local model "down" -> deterministic path
    r = client.post("/api/investigate", json={"question": "Is rainfall changing in Chennai since 2001?"})
    assert r.status_code == 202
    j = wait_job(client, r.json()["job_id"], 60)
    assert j["status"] == "done", j
    rep = j["result"]
    assert rep["plan"]["regions"][0]["name"] == "Chennai"
    assert rep["results"][0]["analysis"]["verdict"]["plain_language"]
    assert rep["explanation"]["source"] in ("deterministic", "local_llm")


def test_investigate_off_topic_is_refused_without_job(client):
    r = client.post("/api/investigate", json={"question": "write a python function to reverse a string"})
    assert r.status_code == 200 and r.json()["on_topic"] is False


def test_compare_question_runs_two_regions(client):
    r = client.post("/api/investigate", json={"question": "compare rainfall in Kerala vs Rajasthan since 2001",
                                              "insights": [], "explain": False})
    j = wait_job(client, r.json()["job_id"], 60)
    assert j["status"] == "done", j
    assert len(j["result"]["results"]) == 2 and "comparison" in j["result"]


def test_demos_listing_and_status(client):
    d = client.get("/api/demos").json()["demos"]
    assert {x["id"] for x in d} >= {"chennai-warming", "opposite-rainfall"}
    st = client.get("/api/sources/status").json()
    assert st["credentials"] == {"earthdata_token": True, "earthdata_login": True, "noaa_cdo_token": True}
    assert "fake-edl-token" not in str(st)               # secrets never leak
    assert st["alerts"]["alerts"]


def test_unknown_job_and_series(client):
    assert client.get("/api/jobs/j_nope").status_code == 404
    assert client.post("/api/analyze", json={"series_id": "s_nope"}).status_code == 404
