"""Connectors against the fake upstream (formats reconstructed from the reference doc)."""
import asyncio
from datetime import date

import numpy as np
import pytest

from backend.catalog.catalog import load_catalog
from backend.connectors.base import FetchRequest
from backend.core.errors import UpstreamUnavailable
from backend.core.geometry import parse_geometry
from backend.core.http import ResilientHTTP
from backend.storage.db import Database
from backend.storage.series_store import SeriesStore
from backend.timeseries.service import TimeSeriesService
from tests.fakes import transport

CHENNAI = {"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"}
BOX = {"type": "BBox", "bbox": [78.0, 10.0, 80.0, 12.0], "name": "Box"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def svc(settings, fake):
    http = ResilientHTTP(settings, transport=transport(fake))
    db = Database(settings.db_path)
    return TimeSeriesService(settings, http, load_catalog(), SeriesStore(settings.series_dir, db))


def test_giovanni_point_chunks_auth_units_and_trend(svc, fake):
    cat = svc.catalog
    raw = run(svc.connectors["giovanni_point"].fetch(
        FetchRequest(cat.get("imerg_precip_daily"), parse_geometry(CHENNAI), date(2001, 1, 1), date(2020, 12, 31))))
    assert raw.meta.units == "mm/day"
    assert np.isnan(raw.value).sum() > 0                 # -9999 fills removed by parser
    n_chunks = sum("timeseries" in c for c in fake.calls)
    assert n_chunks == 3                                 # 8-year chunks for daily data
    # second identical request is a cache hit
    run(svc.connectors["giovanni_point"].fetch(
        FetchRequest(cat.get("imerg_precip_daily"), parse_geometry(CHENNAI), date(2001, 1, 1), date(2020, 12, 31))))
    assert sum("timeseries" in c for c in fake.calls) == n_chunks


def test_retry_on_429(svc, fake):
    fake.fail_once_429.add("api.giovanni.earthdata.nasa.gov/timeseries")
    raw = run(svc.connectors["giovanni_point"].fetch(
        FetchRequest(svc.catalog.get("imerg_precip_monthly"), parse_geometry(CHENNAI), date(2001, 1, 1),
                     date(2010, 12, 31))))
    assert len(raw.value) == 120
    assert svc.http.stats["throttled"] == 1


def test_full_build_series_converts_units_and_recovers_trend(svc):
    from backend.analysis.engine import analyze_series
    out = run(svc.build_series("merra2_t2m", parse_geometry(CHENNAI), date(2001, 1, 1), date(2004, 12, 31)))
    ms = svc.store.load(out["series_id"])
    assert ms.units == "°C"
    assert 20 < np.nanmean(ms.value) < 35                # K -> °C applied
    assert out["completeness"]["n_valid"] == 47          # one -9999 fill masked
    again = run(svc.build_series("merra2_t2m", parse_geometry(CHENNAI), date(2001, 1, 1), date(2004, 12, 31)))
    assert again["cached"] is True
    an = analyze_series(ms, min_months=24)
    assert an["verdict"]["direction"] in ("rising", "falling")


def test_outage_routes_to_opendap_fallback(svc, fake):
    """GLDAS 3H is in the GES DISC outage list -> router must go straight to Cloud OPeNDAP monthly."""
    fake.calls.clear()
    with pytest.raises(UpstreamUnavailable):
        # the fake OPeNDAP only knows T2M/precipitation; GLDAS variable is absent from the DMR
        run(svc.build_series("gldas_tair", parse_geometry(BOX), date(2001, 1, 1), date(2003, 12, 31)))
    assert not any("timeseries" in c for c in fake.calls)
    assert any("opendap" in c for c in fake.calls)


def test_opendap_area_mean_and_point(svc):
    v = svc.catalog.get("merra2_t2m")
    conn = svc.connectors["opendap"]
    raw = run(conn.fetch(FetchRequest(v, parse_geometry(BOX), date(2001, 1, 1), date(2002, 12, 31))))
    assert len(raw.value) == 24 and np.isfinite(raw.value).all()
    assert raw.meta.units == "K"
    assert "cos(latitude)" in " ".join(raw.provenance.notes)
    raw_p = run(conn.fetch(FetchRequest(v, parse_geometry(CHENNAI), date(2001, 1, 1), date(2001, 12, 31))))
    assert len(raw_p.value) == 12


def test_opendap_handles_lon_lat_dimension_order(svc):
    v = svc.catalog.get("imerg_precip_monthly")
    raw = run(svc.connectors["opendap"].fetch(FetchRequest(v, parse_geometry(BOX), date(2001, 1, 1),
                                                           date(2001, 12, 31))))
    assert len(raw.value) == 12 and (raw.value > 0).all()


def test_giovanni_missing_variable_falls_back(svc, fake):
    fake.giovanni_missing.add("GPM_3IMERGM_07_precipitation")
    out = run(svc.build_series("imerg_precip_monthly", parse_geometry(CHENNAI), date(2001, 1, 1),
                               date(2003, 12, 31)))
    assert out["source_api"] == "cloud_opendap"
    assert out["attempts"][0]["status"] == "failed"
    ms = svc.store.load(out["series_id"])
    assert ms.units == "mm/day"


def test_appeears_point_flow_with_qc(svc, fake):
    out = run(svc.build_series("modis_ndvi_monthly", parse_geometry(CHENNAI), date(2001, 1, 1),
                               date(2010, 12, 31)))
    ms = svc.store.load(out["series_id"])
    assert out["qc"]["n_bad_quality_flag"] > 0           # cloudy months removed via pixel_reliability
    assert out["qc"]["n_fill"] > 0
    assert np.nanmax(ms.value) <= 1.0
    assert any("/task/" in c for c in fake.calls)
    # a second request with the same body resumes the stored task instead of resubmitting
    posts = sum(c.startswith("POST") and c.endswith("/task") for c in fake.calls)
    run(svc.build_series("modis_ndvi_monthly", parse_geometry(CHENNAI), date(2001, 1, 1), date(2010, 12, 31),
                         refresh=True))
    assert sum(c.startswith("POST") and c.endswith("/task") for c in fake.calls) == posts


def test_ncei_area_multi_station_anomaly_average(svc):
    out = run(svc.build_series("station_tavg", parse_geometry(BOX), date(2000, 1, 1), date(2010, 12, 31)))
    ms = svc.store.load(out["series_id"])
    assert ms.n_valid >= 120
    assert "multi-station" in " ".join(ms.provenance.notes)


def test_ncei_point_with_explicit_station_needs_no_token(settings, fake):
    settings.noaa_cdo_token = None
    http = ResilientHTTP(settings, transport=transport(fake))
    s = TimeSeriesService(settings, http, load_catalog(), SeriesStore(settings.series_dir, Database(settings.db_path)))
    out = run(s.build_series("station_tavg", parse_geometry(CHENNAI), date(2000, 1, 1), date(2005, 12, 31),
                             options={"stations": ["USW00094728"]}))
    assert out["source_api"] == "ncei.ads"
