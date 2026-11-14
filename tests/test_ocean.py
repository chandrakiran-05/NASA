"""ERDDAP, NSIDC Sea Ice Index and CO-OPS connectors, offline, against REAL responses recorded live on
2026-11-14 (tests/fixtures/recorded/erddap_*, nsidc_*, coops_*)."""
import asyncio
import itertools
import json
import math
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote

import httpx
import numpy as np
import pandas as pd
import pytest

from backend.connectors import erddap
from backend.connectors.base import FetchRequest
from backend.connectors.coops import NOAACoops, _windows
from backend.connectors.erddap import ERDDAPGrid, parse_griddap_csv
from backend.connectors.nsidc_seaice import NSIDCSeaIce
from backend.core.errors import InvalidRequest
from backend.core.geometry import parse_geometry
from backend.core.http import ResilientHTTP
from backend.timeseries.parsers import parse_configured_variables
from backend.timeseries.qc import apply_qc

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "tests" / "fixtures" / "recorded"
CAT = {v["id"]: v for v in json.loads(
    (ROOT / "backend" / "catalog" / "data" / "seed_catalog_ocean_atmos.json").read_text(encoding="ascii"))["variables"]}

# nceiErsstv5_LonPM180, sst[1979:1:2002][(0.0)][50:1:52][129:1:131]: lat 12/14/16, lon 78/80/82, 2019-01..2020-12
ERSST_CSV = (REC / "erddap_ersstv5_chennai_3x3_2019_2020.csv").read_text()
ERSST_LAT = np.arange(-88.0, 89.0, 2.0)            # the live axes: 89 x 180 cells, 2 degrees
ERSST_LON = np.arange(-180.0, 179.0, 2.0)
CHENNAI = {"type": "Point", "coordinates": [80.27, 13.08]}
_N = itertools.count()


def run(coro):
    return asyncio.run(coro)


def http_for(settings, handler, calls):
    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(unquote(str(request.url)))
        return handler(request)
    # own raw-response cache per client, so one test's answers never leak into the next client
    fresh = settings.model_copy(update={"data_dir": settings.data_dir / f"http{next(_N)}"})
    return ResilientHTTP(fresh, transport=httpx.MockTransport(wrapped))


def erddap_handler(csv: str = ERSST_CSV, lon_axis: np.ndarray = ERSST_LON):
    """Axis queries get the axes; data queries get the recorded rows for the requested time indices."""
    rows = csv.splitlines()
    times = sorted({r.split(",")[0] for r in rows[2:]})

    def handler(request):
        q = unquote(request.url.query.decode())
        if request.url.path.endswith(".csv0"):
            axis = {"time": times, "latitude": ERSST_LAT, "longitude": lon_axis}[q.split("[")[0]]
            return httpx.Response(200, text="\n".join(map(str, axis)) + "\n")
        a, b = (int(x) for x in q.split("[")[1].split("]")[0].split(":")[::2])
        keep = set(times[a:b + 1])
        return httpx.Response(200, text="\n".join(rows[:2] + [r for r in rows[2:] if r.split(",")[0] in keep]) + "\n")
    return handler


def fixture_frame() -> pd.DataFrame:
    df, _ = parse_griddap_csv(ERSST_CSV, "sst")
    return df


# ------------------------------------------------------------------ ERDDAP
def test_griddap_csv_parser_keeps_land_as_nan():
    df, units = parse_griddap_csv(ERSST_CSV, "sst")
    assert units == "degree_C" and len(df) == 24 * 9
    assert df["sst"].isna().sum() == 24 * 6                 # lon 78 and 80 are land cells near Chennai
    assert df.loc[df["longitude"] == 82.0, "sst"].between(24, 32).all()


def test_erddap_point_uses_nearest_grid_cell_with_data(settings):
    calls = []
    conn = ERDDAPGrid(settings, http_for(settings, erddap_handler(), calls))
    raw = run(conn.fetch(FetchRequest(CAT["sst"], parse_geometry(CHENNAI), date(2019, 1, 1), date(2020, 12, 31))))
    data_q = [c for c in calls if ".csv?" in c]
    assert data_q == ["https://coastwatch.pfeg.noaa.gov/erddap/griddap/nceiErsstv5_LonPM180.csv?"
                      "sst[0:1:23][(0.0)][50:1:52][129:1:131]"]
    df = fixture_frame()
    want = df[(df["latitude"] == 14.0) & (df["longitude"] == 82.0)].sort_values("time")["sst"].to_numpy()
    assert len(raw.value) == 24 and np.allclose(raw.value, want)
    assert raw.native_resolution == "monthly" and raw.meta.units == "degree_C"
    p = raw.provenance
    assert p.doi == "10.7289/V5T72FNM" and p.dataset_short_name == "nceiErsstv5_LonPM180" and p.retrieved_at
    assert p.version == "v5" and "nceiErsstv5_LonPM180.csv" in p.request_url
    assert any("lat=14.0, lon=82.0" in n for n in p.notes)


def test_erddap_area_mean_is_cos_lat_weighted_over_valid_cells(settings, monkeypatch):
    calls = []
    conn = ERDDAPGrid(settings, http_for(settings, erddap_handler(), calls))
    box = parse_geometry({"type": "BBox", "bbox": [77, 11, 83, 17]})
    raw = run(conn.fetch(FetchRequest(CAT["sst"], box, date(2019, 1, 1), date(2020, 12, 31))))
    assert any("[50:1:52][129:1:131]" in c for c in calls)
    df = fixture_frame().dropna()
    df["w"] = np.cos(np.deg2rad(df["latitude"]))
    want = df.groupby("time").apply(lambda g: (g["sst"] * g["w"]).sum() / g["w"].sum(), include_groups=False)
    assert np.allclose(raw.value, want.to_numpy())
    assert any("cos(latitude)" in n for n in raw.provenance.notes)

    # one month with only 1 of 3 sea cells valid: kept at the 30 % rule, dropped at a 50 % rule
    rows = ERSST_CSV.splitlines()
    sparse = "\n".join(rows[:2] + [r for r in rows[2:] if not (r.startswith("2019-01-15") and
                                                                 (",14.0,82.0," in r or ",16.0,82.0," in r))])
    raw30 = run(ERDDAPGrid(settings, http_for(settings, erddap_handler(sparse), [])).fetch(
        FetchRequest(CAT["sst"], box, date(2019, 1, 1), date(2020, 12, 31))))
    assert np.isfinite(raw30.value[0])
    monkeypatch.setattr(erddap, "MIN_VALID_FRACTION", 0.5)
    raw50 = run(ERDDAPGrid(settings, http_for(settings, erddap_handler(sparse), [])).fetch(
        FetchRequest(CAT["sst"], box, date(2019, 1, 1), date(2020, 12, 31))))
    assert np.isnan(raw50.value[0]) and np.isfinite(raw50.value[1:]).all()


def test_erddap_large_box_uses_stride_and_time_chunks(settings):
    calls = []
    conn = ERDDAPGrid(settings, http_for(settings, erddap_handler(), calls))
    world = parse_geometry({"type": "BBox", "bbox": [-180, -88, 178, 88]})
    raw = run(conn.fetch(FetchRequest(CAT["sst"], world, date(2019, 1, 1), date(2020, 12, 31))))
    data_q = [c for c in calls if ".csv?" in c]
    # 16 020 cells x 24 months > 200 000 values -> every 2nd cell; 4 050 cells/step -> 12 months per request
    assert [q.split("?")[1] for q in data_q] == ["sst[0:1:11][(0.0)][0:2:88][0:2:179]",
                                                 "sst[12:1:23][(0.0)][0:2:88][0:2:179]"]
    assert len(raw.value) == 24 and "2 request chunk(s)" in raw.provenance.notes


def test_erddap_lon360_dataset(settings):
    calls = []
    v = {**CAT["sst"], "erddap_lon360": True}
    shifted = ERSST_CSV.replace(",78.0,", ",278.0,").replace(",80.0,", ",280.0,").replace(",82.0,", ",282.0,")
    conn = ERDDAPGrid(settings, http_for(settings, erddap_handler(shifted, np.arange(0.0, 359.0, 2.0)), calls))
    pt = parse_geometry({"type": "Point", "coordinates": [-79.73, 13.08]})
    raw = run(conn.fetch(FetchRequest(v, pt, date(2019, 1, 1), date(2020, 12, 31))))
    assert any("[50:1:52][139:1:141]" in c for c in calls)      # -79.73 -> 280.27 -> index 140
    assert any("lat=14.0, lon=-78.0" in n for n in raw.provenance.notes)
    with pytest.raises(InvalidRequest):
        run(conn.fetch(FetchRequest(v, parse_geometry({"type": "BBox", "bbox": [-5, 10, 5, 20]}),
                                    date(2019, 1, 1), date(2020, 12, 31))))


# ------------------------------------------------------------------ NSIDC Sea Ice Index
SII_HEADER = "year, mo,source_dataset, region, extent,   area\n"
SII_DEC = (REC / "nsidc_N_12_extent_v4.0.csv").read_text()


def sii_handler(request):
    # only December was recorded; other months answer with the real header and no rows
    return httpx.Response(200, text=SII_DEC if request.url.path.endswith("_12_extent_v4.0.csv") else SII_HEADER)


def test_seaice_north_parses_sentinel_and_says_hemisphere_wide(settings):
    calls = []
    conn = NSIDCSeaIce(settings, http_for(settings, sii_handler, calls))
    arctic = parse_geometry({"type": "Point", "coordinates": [-150.0, 75.0]})
    raw = run(conn.fetch(FetchRequest(CAT["seaice_extent"], arctic, date(1979, 1, 1), date(2024, 12, 31))))
    assert len(calls) == 12 and all("/north/monthly/data/N_" in c for c in calls)
    t = pd.DatetimeIndex(raw.time)
    assert len(raw.value) == 46 and (t.month == 12).all()
    assert raw.value[t.year.get_loc(1979)] == pytest.approx(13.34)
    assert np.isnan(raw.value[t.year.get_loc(1987)])               # -9999 -> NaN
    p = raw.provenance
    assert p.dataset_short_name == "G02135" and p.version == "4.0" and p.doi == "10.7265/a98x-0f50"
    assert any("hemisphere-wide value, not a value for the drawn" in n for n in p.notes)
    assert any("NSIDC-0051" in n for n in p.notes)


def test_seaice_south_and_tropics(settings):
    calls = []
    conn = NSIDCSeaIce(settings, http_for(settings, sii_handler, calls))
    weddell = parse_geometry({"type": "BBox", "bbox": [-60, -80, -20, -60]})
    raw = run(conn.fetch(FetchRequest(CAT["seaice_extent"], weddell, date(1979, 1, 1), date(1990, 12, 31))))
    assert all("/south/monthly/data/S_" in c for c in calls)
    assert any(n.startswith("Southern Hemisphere") for n in raw.provenance.notes)
    calls.clear()
    with pytest.raises(InvalidRequest, match="40"):
        run(conn.fetch(FetchRequest(CAT["seaice_extent"], parse_geometry(CHENNAI), date(1979, 1, 1),
                                    date(1990, 12, 31))))
    assert calls == []


# ------------------------------------------------------------------ CO-OPS tide gauges
COOPS_MM = (REC / "coops_monthly_mean_8518750_2003_2004.json").read_text()
COOPS_ST = (REC / "coops_stations_waterlevels_subset.json").read_text()
NO_DATA = '{"error": {"message":"No data was found. This product may not be offered at this station."}}'


def coops_handler(request):
    if request.url.path.endswith("/stations.json"):
        return httpx.Response(200, text=COOPS_ST)
    q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
    ok = q["station"] == "8518750" and q["begin_date"] >= "19000101"
    return httpx.Response(200, text=COOPS_MM if ok else NO_DATA)


def test_coops_nearest_station_msl_and_inferred_months(settings):
    calls = []
    conn = NOAACoops(settings, http_for(settings, coops_handler, calls))
    manhattan = parse_geometry({"type": "Point", "coordinates": [-74.02, 40.69]})
    raw = run(conn.fetch(FetchRequest(CAT["tide_gauge_msl"], manhattan, date(2003, 1, 1), date(2004, 12, 31))))
    q = parse_qs(calls[-1].split("?")[1])
    assert q["station"] == ["8518750"] and q["product"] == ["monthly_mean"] and q["datum"] == ["MSL"]
    assert q["units"] == ["metric"] and q["begin_date"] == ["20030101"] and q["end_date"] == ["20041231"]
    assert len(raw.value) == 24 and raw.value[0] == pytest.approx(-0.109) and raw.meta.units == "m"
    inferred = [(t.year, t.month) for t, ok in zip(pd.DatetimeIndex(raw.time), raw.qc_pass) if not ok]
    assert inferred == [(2004, 2), (2004, 3), (2004, 4), (2004, 5)]   # inferred=13
    clean, report = apply_qc(raw)
    assert report["n_bad_quality_flag"] == 4 and np.isnan(clean.value[13:17]).all()
    notes = " ".join(raw.provenance.notes)
    assert "8518750 The Battery" in notes and "km from the requested place" in notes and "4 month(s)" in notes
    assert raw.provenance.request_url.startswith("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter")


def test_coops_skips_great_lakes_and_far_places(settings):
    conn = NOAACoops(settings, http_for(settings, coops_handler, []))
    buffalo = parse_geometry({"type": "Point", "coordinates": [-78.89, 42.88]})   # only a non-tidal gauge nearby
    with pytest.raises(InvalidRequest, match="tide gauge"):
        run(conn.fetch(FetchRequest(CAT["tide_gauge_msl"], buffalo, date(2003, 1, 1), date(2004, 12, 31))))


def test_coops_station_override_and_windows(settings):
    calls = []
    conn = NOAACoops(settings, http_for(settings, coops_handler, calls))
    raw = run(conn.fetch(FetchRequest(CAT["tide_gauge_msl"], parse_geometry(CHENNAI), date(1850, 1, 1),
                                      date(2004, 12, 31), {"station_id": "8518750"})))
    assert not any("stations.json" in c for c in calls)
    assert len(calls) == 2 and len(raw.value) == 24          # 1850-1949 window has no data and is skipped
    wins = _windows(date(1800, 1, 1), date(2025, 12, 31))
    assert wins[0] == (date(1800, 1, 1), date(1899, 12, 31)) and wins[-1][1] == date(2025, 12, 31)
    assert all((b - a).days < 73000 for a, b in wins)


# ------------------------------------------------------------------ catalog
def test_ocean_atmos_catalog_entries():
    assert {"sst", "modis_chlorophyll", "seaice_extent", "tide_gauge_msl", "merra2_wind_speed", "merra2_aod",
            "airs_total_ozone", "merra2_tropopause_temp", "merra2_skin_temp"} == set(CAT)
    official = set(parse_configured_variables((REC / "giovanni_configured_variables.json").read_text()))
    for v in CAT.values():
        ds = v["dataset"]
        assert ds.get("doi") or ds.get("url"), v["id"]
        assert v["name"] and v["short_definition"] and v["definition"] and v["keywords"] and v["verified_note"]
        if v["source"] == "giovanni":
            assert v["giovanni_id"] in official
            # point mode needs a monthly Giovanni id
            assert ("point" in v["spatial_modes"]) == (v.get("giovanni_point_resolution") == "monthly")
            assert v.get("giovanni_point_id", v["giovanni_id"]) in official
    assert "prescribed sea-surface temperature" in CAT["merra2_skin_temp"]["definition"]
    assert CAT["tide_gauge_msl"]["spatial_modes"] == ["point"]
    assert math.isclose(CAT["sst"]["erddap_zdim"], 0.0)
