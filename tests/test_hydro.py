"""Hydrology connectors (USGS NWIS, SWOT Hydrocron) and WaterML export, offline against REAL responses
recorded live on 2026-11-14 (tests/fixtures/recorded/usgs_* and swot_*)."""
import asyncio
import io
import json
import math
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from backend.catalog.catalog import DATA
from backend.connectors.base import FetchRequest
from backend.connectors.swot import SwotHydrocron
from backend.connectors.usgs_nwis import USGSNwis
from backend.core.errors import InvalidRequest, UpstreamUnavailable
from backend.core.geometry import parse_geometry
from backend.core.http import ResilientHTTP
from backend.timeseries.model import MonthlySeries, Provenance
from backend.timeseries.qc import apply_qc, convert_units
from backend.timeseries.resample import to_monthly
from backend.timeseries.service import norm_units
from backend.timeseries.waterml import NS, to_cuahsi_csv, to_waterml2

REC = Path(__file__).parent / "fixtures" / "recorded"
DV = "usgs_dv_15453500_00060_2026-09-15_2026-11-13.json"          # Yukon R, AK: 36 values, 13 Eqp, 11 Ice
OGC = "usgs_ogc_daily_15453500_00060_2026-09-15_2026-11-13.json"   # same days from the OGC API
REACH = "swot_reach_78340600051_2024-01-25_2024-03-29.json"
LAKE = "swot_lake_6350036102_2023-08_2023-10.json"
HYDRO = {v["id"]: v for v in json.loads((DATA / "seed_catalog_hydro.json").read_text(encoding="utf-8"))["variables"]}
DC_BOX = {"type": "BBox", "bbox": [-77.4, 38.8, -77.0, 39.1], "name": "Washington DC"}
ROCK_CREEK = {"type": "Point", "coordinates": [-77.04, 38.97]}


def run(coro):
    return asyncio.run(coro)


def http_for(settings, handler):
    calls = []

    def h(request):
        calls.append(request.url)
        return handler(request)
    return ResilientHTTP(settings, transport=httpx.MockTransport(h)), calls


def usgs_handler(dv_status=200, sites_status=200):
    def h(request):
        p, q = request.url.path, request.url.params
        if p == "/nwis/site/":
            name = "usgs_site_15453500.rdb" if "sites" in q else "usgs_site_bbox_dc_00060.rdb"
            return httpx.Response(sites_status, content=(REC / name).read_bytes() if sites_status == 200 else b"")
        if p == "/nwis/dv/":
            return httpx.Response(dv_status, content=(REC / DV).read_bytes() if dv_status == 200 else b"down")
        if request.url.host == "api.waterdata.usgs.gov":
            return httpx.Response(200, content=(REC / OGC).read_bytes())
        return httpx.Response(404)
    return h


def yukon_request(**opts):
    return FetchRequest(HYDRO["usgs_streamflow"], parse_geometry(ROCK_CREEK), date(2026, 9, 15), date(2026, 11, 13),
                        {"site_id": "15453500", **opts})


# ------------------------------------------------------------------ USGS site discovery
def test_usgs_area_picks_largest_drainage_area(settings):
    http, _ = http_for(settings, usgs_handler())
    sites = run(USGSNwis(settings, http).find_sites(parse_geometry(DC_BOX), ["00060"], date(2015, 1, 1),
                                                    date(2020, 12, 31), "ST"))
    assert sites[0]["site_no"] == "01646500"           # Potomac at Little Falls, 11560 mi2 (tie with the
    assert float(sites[0]["drain_area_va"]) == 11560   # "adjusted" series 01646502 broken by site number)


def test_usgs_point_picks_nearest_gauge(settings):
    http, calls = http_for(settings, usgs_handler())
    sites = run(USGSNwis(settings, http).find_sites(parse_geometry(ROCK_CREEK), ["00060"], date(2015, 1, 1),
                                                    date(2020, 12, 31)))
    assert sites[0]["site_no"] == "01648000"           # Rock Creek at Sherrill Drive, ~0.3 km away
    assert sites[1]["site_no"] == "01648010"           # Rock Creek at Joyce Rd, ~1.1 km away
    assert calls[0].params["bBox"] == "-77.290000,38.720000,-76.790000,39.220000"


def test_usgs_point_widens_once_then_fails_clearly(settings):
    http, calls = http_for(settings, usgs_handler(sites_status=404))   # NWIS answers 404 for "no sites"
    req = FetchRequest(HYDRO["usgs_streamflow"], parse_geometry(ROCK_CREEK), date(2015, 1, 1), date(2020, 12, 31))
    with pytest.raises(UpstreamUnavailable, match="options.site_id"):
        run(USGSNwis(settings, http).fetch(req))
    assert len(calls) == 2 and "-77.540000" in str(calls[1])          # 0.25 deg, then 0.5 deg


# ------------------------------------------------------------------ USGS values, flags, provenance
def test_usgs_dv_flags_and_nodata_are_masked_with_full_provenance(settings):
    http, _ = http_for(settings, usgs_handler())
    raw = run(USGSNwis(settings, http).fetch(yukon_request()))
    assert len(raw.value) == 60 and raw.native_resolution == "daily" and raw.meta.units == "ft3/s"
    assert (~raw.qc_pass).sum() == 24                  # 13 "Eqp" + 11 "Ice" days
    qc, rep = apply_qc(raw)
    assert rep["n_fill"] == 24 and rep["n_valid"] == 36
    assert np.isnan(qc.value[~raw.qc_pass]).all() and np.isfinite(qc.value[raw.qc_pass]).all()
    p = raw.provenance
    assert p.source_api == "usgs.nwis_dv" and p.doi == "10.5066/F7P55KJN" and p.product_id == "USGS-15453500"
    assert "sites=15453500" in p.request_url and p.retrieved_at
    notes = " ".join(p.notes)
    assert "YUKON R NR STEVENS VILLAGE AK" in notes and "65.875556" in notes and "194000 mi2" in notes
    assert "provisional values: 60 of 60" in notes and "site given by user" in notes


def test_usgs_falls_back_to_ogc_api_and_agrees_with_legacy(settings, tmp_path):
    http, _ = http_for(settings, usgs_handler())
    legacy = run(USGSNwis(settings, http).fetch(yukon_request()))
    settings.data_dir = tmp_path / "other"             # fresh raw cache
    http2, calls = http_for(settings, usgs_handler(dv_status=503))
    ogc = run(USGSNwis(settings, http2).fetch(yukon_request()))
    assert ogc.provenance.source_api == "usgs.ogcapi_daily"
    assert any("OGC API" in n for n in ogc.provenance.notes)
    assert norm_units(ogc.meta.units) == norm_units(legacy.meta.units) == "ft3/s"   # "ft^3/s" vs "ft3/s"
    a, b = apply_qc(legacy)[0], apply_qc(ogc)[0]
    assert np.array_equal(a.time, b.time)
    assert np.array_equal(a.value, b.value, equal_nan=True)                # two real services, same numbers


def test_usgs_monthly_uses_completeness_rule_and_never_fills(settings):
    http, _ = http_for(settings, usgs_handler())
    raw, _ = apply_qc(run(USGSNwis(settings, http).fetch(yukon_request())))
    raw = convert_units(raw, HYDRO["usgs_streamflow"]["convert"]["factor"], 0.0, "m3/s")
    ms = to_monthly(raw, start=date(2026, 9, 1), end=date(2026, 11, 30), min_valid_fraction=0.7)
    s = pd.Series(raw.value, index=pd.DatetimeIndex(raw.time)).dropna()
    for t, v in zip(ms.time, ms.value):
        days = s[s.index.to_period("M") == t.to_period("M")]
        if len(days) / t.days_in_month >= 0.7:
            assert v == pytest.approx(days.mean())
        else:
            assert math.isnan(v)
    assert ms.n == 3


# ------------------------------------------------------------------ SWOT Hydrocron
def swot_handler(name=None, status=200):
    def h(request):
        assert request.url.params["collection_name"] in ("SWOT_L2_HR_RiverSP_D", "SWOT_L2_HR_LakeSP_D")
        if status != 200:
            return httpx.Response(status, json={"error": "400: Results with the specified Feature ID 1 were not found"})
        return httpx.Response(200, content=(REC / name).read_bytes())
    return h


def test_swot_reach_drops_fills_and_no_data(settings):
    http, _ = http_for(settings, swot_handler(REACH))
    req = FetchRequest(HYDRO["swot_river_wse"], parse_geometry(ROCK_CREEK), date(2024, 1, 25), date(2024, 3, 29),
                       {"feature_id": "78340600051"})
    raw = run(SwotHydrocron(settings, http).fetch(req))
    assert len(raw.value) == 10                         # 12 rows minus 2 "no_data" passes
    qc, rep = apply_qc(raw)
    assert rep["n_fill"] == 1 and rep["n_valid"] == 9   # -999999999999.0 on 2024-02-09
    assert np.nanmin(qc.value) > 380 and np.nanmax(qc.value) < 390
    p = raw.provenance
    assert (p.doi, p.version, p.dataset_short_name) == ("10.5067/SWOT-RIVERSP-D", "D", "SWOT_L2_HR_RiverSP_D")
    assert "feature_id=78340600051" in p.request_url and p.product_id == "Reach 78340600051"
    assert any("too short" in n for n in p.notes)
    ms = to_monthly(qc, start=date(2024, 1, 1), end=date(2024, 3, 31))
    assert ms.value[1] == pytest.approx(np.mean([386.9557, 387.0513, 386.5979, 386.6074]))   # Feb passes


def test_swot_lake_drops_repeated_rows_and_bad_quality(settings):
    http, _ = http_for(settings, swot_handler(LAKE))
    req = FetchRequest(HYDRO["swot_lake_wse"], parse_geometry(ROCK_CREEK), date(2023, 8, 1), date(2023, 10, 31),
                       {"feature_id": "6350036102"})
    raw = run(SwotHydrocron(settings, http).fetch(req))
    assert len(raw.value) == 7                          # 10 rows - 1 no_data - 2 verbatim repeats
    qc, rep = apply_qc(raw)
    assert rep["n_bad_quality_flag"] == 1 and rep["n_valid"] == 6       # quality_f = 3 (bad) on 2023-09-16
    ms = to_monthly(qc, start=date(2023, 8, 1), end=date(2023, 10, 31))
    assert ms.value[0] == pytest.approx((260.854 + 260.831) / 2) and math.isnan(ms.value[1])


def test_swot_needs_feature_id_and_reports_missing_data(settings):
    http, _ = http_for(settings, swot_handler(status=400))
    conn = SwotHydrocron(settings, http)
    base = (HYDRO["swot_river_wse"], parse_geometry(ROCK_CREEK), date(2023, 7, 1), date(2025, 12, 31))
    with pytest.raises(InvalidRequest, match="feature_id"):
        run(conn.fetch(FetchRequest(*base)))
    with pytest.raises(UpstreamUnavailable, match="no Reach 1 observations"):
        run(conn.fetch(FetchRequest(*base, {"feature_id": "1"})))


# ------------------------------------------------------------------ WaterML 2.0 / CUAHSI CSV
def monthly_example() -> MonthlySeries:
    prov = Provenance("usgs.nwis_dv", "00060", {"type": "Point", "coordinates": [-77.1, 38.9], "name": "Potomac"},
                      dataset_short_name="USGS NWIS daily values", product_id="USGS-01646500", doi="10.5066/F7P55KJN",
                      retrieved_at="2026-11-14T14:00:00+00:00", notes=["site USGS-01646500"])
    return MonthlySeries(pd.date_range("2020-01-01", periods=6, freq="MS"),
                         [1.5, np.nan, 2.25, 0.1 + 0.2, np.nan, -3.0], "m³/s", prov, variable_id="usgs_streamflow")


def test_waterml2_parses_and_round_trips_values_and_nans():
    ms = monthly_example()
    root = ET.fromstring(to_waterml2(ms, series_id="s_abc", variable=HYDRO["usgs_streamflow"]))
    assert root.tag == f"{{{NS['wml2']}}}Collection"
    w, x = f"{{{NS['wml2']}}}", f"{{{NS['xlink']}}}"
    assert "10.5066/F7P55KJN" in root.find(f"{{{NS['gml']}}}description").text
    assert root.find(f".//{w}DefaultTVPMeasurementMetadata/{w}uom").get("code") == "m³/s"
    tvps = root.findall(f".//{w}point/{w}MeasurementTVP")
    assert [t.find(f"{w}time").text for t in tvps] == [f"2020-{m:02d}-01T00:00:00Z" for m in range(1, 7)]
    back = []
    for t in tvps:
        v = t.find(f"{w}value")
        if v.get(f"{{{NS['xsi']}}}nil") == "true":
            assert t.find(f".//{w}nilReason").get(f"{x}href").endswith("/missing") and not v.text
            back.append(np.nan)
        else:
            back.append(float(v.text))
    assert np.array_equal(np.array(back), ms.value, equal_nan=True)     # exact, including 0.1 + 0.2


def test_cuahsi_csv_has_metadata_header_and_missing_qualifier():
    ms = monthly_example()
    text = to_cuahsi_csv(ms, series_id="s_abc", variable=HYDRO["usgs_streamflow"])
    head = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert any("doi.org/10.5066/F7P55KJN" in ln for ln in head) and any("retrieved_at" in ln for ln in head)
    assert any("USGS-01646500" in ln for ln in head)
    df = pd.read_csv(io.StringIO(text), comment="#", keep_default_na=False, dtype=str)
    assert list(df.columns) == ["DateTime", "Value", "Qualifier"]
    assert list(df["Qualifier"]) == ["", "missing", "", "", "missing", ""]
    vals = [float(v) if v != "" else np.nan for v in df["Value"]]
    assert np.array_equal(np.array(vals), ms.value, equal_nan=True)


# ------------------------------------------------------------------ catalog entries
def test_hydro_catalog_entries_are_complete_and_ids_are_real():
    assert set(HYDRO) == {"usgs_streamflow", "usgs_gage_height", "usgs_reservoir_elevation", "nldas_streamflow",
                          "gldas_baseflow", "swot_river_wse", "swot_lake_wse"}
    listing = set(json.loads((REC / "giovanni_configured_variables.json").read_text())["configured_variables"])
    for v in HYDRO.values():
        for k in ("name", "short_definition", "definition", "keywords", "domain", "family", "units", "source",
                  "spatial_modes", "dataset", "verified"):
            assert v.get(k) not in (None, "", []), (v["id"], k)
        assert v["dataset"].get("doi") or v["dataset"].get("url"), v["id"]
        assert v["source"] in ("usgs_nwis", "giovanni", "swot_hydrocron")
        for k in ("giovanni_id", "giovanni_point_id"):
            if v.get(k):
                assert v[k] in listing, v[k]
    assert HYDRO["swot_lake_wse"]["requires_option"] == "feature_id" and "too short" in HYDRO["swot_lake_wse"]["definition"]
