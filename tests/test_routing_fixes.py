"""Routing fixes: point/area fallback geometry, cache keys, plain credentials message, catalog routes."""
import asyncio
from datetime import date

import pytest

from backend.catalog.catalog import load_catalog
from backend.catalog.router import plan_routes
from backend.core.geometry import parse_geometry
from backend.core.http import ResilientHTTP
from backend.storage.db import Database
from backend.storage.series_store import SeriesStore
from backend.timeseries.service import TimeSeriesService
from tests.conftest import wait_job
from tests.fakes import transport

BOX = {"type": "BBox", "bbox": [-91.0, 38.0, -90.0, 39.0], "name": "St Louis"}
POINT = {"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"}


@pytest.fixture
def svc(settings, fake):
    http = ResilientHTTP(settings, transport=transport(fake))
    return TimeSeriesService(settings, http, load_catalog(),
                             SeriesStore(settings.series_dir, Database(settings.db_path)))


def run(coro):
    return asyncio.run(coro)


def test_point_only_variable_on_box_uses_centroid(svc, fake):
    out = run(svc.build_series("nldas_streamflow", parse_geometry(BOX), date(2001, 1, 1), date(2003, 12, 31)))
    assert any("used the centre point of the drawn area" in n for n in out["notes"])
    assert out["source_api"] == "giovanni.timeseries"
    ms = svc.store.load(out["series_id"])
    assert ms.provenance.geometry["coordinates"] == [-90.5, 38.5]      # centroid sent to Giovanni /timeseries
    assert any("centre point" in n for n in ms.provenance.notes)


def test_area_only_variable_on_point_uses_small_box(svc):
    v = svc.catalog.get("merra2_skin_temp")
    eff, note = svc.effective_region(v, parse_geometry(POINT))
    assert eff.kind == "bbox" and eff.bbox == pytest.approx((80.02, 12.83, 80.52, 13.33))
    assert "small box" in note
    out = run(svc.build_series("merra2_skin_temp", parse_geometry(POINT), date(2001, 1, 1), date(2003, 12, 31)))
    assert out["source_api"] == "giovanni.harmony_area"
    assert any("small box" in n for n in out["notes"])


def test_cache_key_includes_effective_geometry(svc):
    v = svc.catalog.get("nldas_streamflow")
    box, centre = parse_geometry(BOX), parse_geometry({"type": "Point", "coordinates": [-90.5, 38.5]})
    a, b = date(2001, 1, 1), date(2003, 12, 31)
    assert svc.request_hash(v, box, a, b, {}) != svc.request_hash(v, centre, a, b, {})
    # variables that support both modes keep their old key (existing caches stay valid)
    from backend.storage.series_store import hash_request
    t2m = svc.catalog.get("merra2_t2m")
    assert svc.request_hash(t2m, box, a, b, {}) == hash_request("merra2_t2m", box.key(), a.isoformat(),
                                                                b.isoformat(), {})


@pytest.fixture
def no_creds(settings, monkeypatch):
    import httpx

    from backend.core import auth
    settings.earthdata_token = settings.earthdata_username = settings.earthdata_password = None
    monkeypatch.setattr(auth, "_token_via_earthaccess", lambda s: None)    # never read the developer's ~/.netrc

    def no_netrc(*a, **k):
        raise FileNotFoundError("no .netrc")
    monkeypatch.setattr(httpx, "NetRCAuth", no_netrc)


def test_missing_credentials_message_is_plain(no_creds, client):
    r = client.post("/api/timeseries", json={"variable_id": "merra2_t2m", "geometry": POINT,
                                             "start": "2001-01", "end": "2003-12"})
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "error"
    assert j["error"]["code"] == "credentials_missing"
    msg = j["error"]["message"]
    assert msg.count("needs a free NASA Earthdata token (EARTHDATA_TOKEN in .env)") == 1
    assert "OPeNDAP" not in msg and "netrc" not in msg


def test_fixed_catalog_entries_have_routes():
    cat = load_catalog()
    box, pt = parse_geometry(BOX), parse_geometry(POINT)
    for vid in ("merra2_t2m_daily_max", "ocean_chlorophyll", "grace_groundwater", "omi_no2_trop",
                "omi_ozone_total", "omi_aerosol_index"):
        v = cat.get(vid)
        assert v["dataset"]["concept_id"], vid
        for region in (box, pt):
            routes, _ = plan_routes(v, region, cat)
            assert routes, (vid, region.kind)
    assert cat.get("merra2_t2m_daily_max")["fallback"]["concept_id"] == "C1276812828-GES_DISC"
    assert cat.get("ocean_chlorophyll")["fallback"]["variable"] == "tot"
