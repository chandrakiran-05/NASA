"""Keyless global grids (seed_catalog_global.json) through the ERDDAP connector, offline, against REAL responses
recorded live on 2026-11-15 from upwell.pfeg.noaa.gov (tests/fixtures/recorded/erddap_global_*)."""
import json
from datetime import date

import httpx
import numpy as np
import pytest

from backend.catalog.catalog import load_catalog
from backend.connectors.base import FetchRequest
from backend.connectors.erddap import ERDDAPGrid, parse_griddap_csv
from backend.core.errors import UpstreamError
from backend.core.geometry import parse_geometry
from tests.test_ocean import REC, ROOT, http_for, run

CAT = {v["id"]: v for v in json.loads(
    (ROOT / "backend" / "catalog" / "data" / "seed_catalog_global.json").read_text(encoding="utf-8"))["variables"]}
LAT = np.array((REC / "erddap_global_ncep_t62_latitude.csv0").read_text().split(), float)   # Gaussian, N -> S
LON = np.arange(0.0, 358.2, 1.875)                                                            # 0..360
T2M = (REC / "erddap_global_t2m_r1_chennai_3x3_2019_2020.csv").read_text()     # air[..][39:41][42:44]
PRECIP = (REC / "erddap_global_precip_r2_buenosaires_3x3_2019_2020.csv").read_text()  # prate[..][64:66][160:162]
SPAN = (date(2019, 1, 1), date(2020, 12, 31))


def handler(csv: str, offline: tuple = ()):
    rows = csv.splitlines()
    times = sorted({r.split(",")[0] for r in rows[2:]})

    def h(request):
        if any(d in request.url.path for d in offline):
            return httpx.Response(404, text="Currently unknown datasetID")
        q = request.url.query.decode()
        if request.url.path.endswith(".csv0"):
            axis = {"time": times, "latitude": LAT, "longitude": LON}[q.split("%5B")[0].split("[")[0]]
            return httpx.Response(200, text="\n".join(map(str, axis)) + "\n")
        return httpx.Response(200, text=csv)
    return h


def fetch(settings, vid, csv, geom, calls, offline=()):
    conn = ERDDAPGrid(settings, http_for(settings, handler(csv, offline), calls))
    return run(conn.fetch(FetchRequest(CAT[vid], parse_geometry(geom), *SPAN)))


def test_catalog_entries_load_and_are_keyless():
    cat = load_catalog()
    for vid in ("global_t2m", "global_precip", "global_soil_moisture", "global_humidity"):
        v = cat.get(vid)
        assert v["source"] == "erddap" and v["erddap_lon360"] and v["verified"]
        assert v["spatial_modes"] == ["point", "area"] and v["dataset"]["doi"] and v["dataset"]["url"]
    assert cat.get("global_t2m")["convert"]["offset"] == -273.15
    assert cat.get("global_precip")["convert"]["factor"] == 86400.0


def test_t2m_point_chennai_parses_kelvin_and_uses_nearest_cell(settings):
    calls = []
    raw = fetch(settings, "global_t2m", T2M, {"type": "Point", "coordinates": [80.27, 13.08]}, calls)
    assert any("air[0:1:23][39:1:41][42:1:44]" in c for c in calls)        # lat 12.38 = idx 40, lon 80.625 = idx 43
    df, units = parse_griddap_csv(T2M, "air")
    assert units == "degK" and raw.meta.units == "degK" and len(raw.value) == 24
    want = df[(df["latitude"] == 12.3808) & (df["longitude"] == 80.625)].sort_values("time")["air"].to_numpy()
    assert np.allclose(raw.value, want) and 290 < np.mean(raw.value) < 310
    assert any("lat=12.3808, lon=80.625" in n for n in raw.provenance.notes)


def test_precip_western_hemisphere_point_maps_to_0_360(settings):
    calls = []
    raw = fetch(settings, "global_precip", PRECIP, {"type": "Point", "coordinates": [-58.38, -34.60]}, calls)
    assert any("prate[0:1:23][64:1:66][160:1:162]" in c for c in calls)    # -58.38 -> 301.62 -> idx 161
    assert any("lon=-58.125" in n for n in raw.provenance.notes)            # reported back in -180..180
    assert 1e-6 < np.nanmean(raw.value) < 1e-4                              # kg m-2 s-1 (x86400 = mm/day)


def test_precip_area_mean_is_cos_lat_weighted(settings):
    raw = fetch(settings, "global_precip", PRECIP, {"type": "BBox", "bbox": [-60.5, -37, -56, -32]}, [])
    df, _ = parse_griddap_csv(PRECIP, "prate")
    df["w"] = np.cos(np.deg2rad(df["latitude"]))
    want = df.groupby("time").apply(lambda g: (g["prate"] * g["w"]).sum() / g["w"].sum(), include_groups=False)
    assert np.allclose(raw.value, want.to_numpy())


def test_offline_copy_falls_back_to_alt_dataset(settings):
    calls = []
    raw = fetch(settings, "global_t2m", T2M, {"type": "Point", "coordinates": [80.27, 13.08]}, calls,
                offline=(CAT["global_t2m"]["dataset_id"],))
    alt = CAT["global_t2m"]["erddap_alt_dataset_ids"][0]
    assert raw.provenance.dataset_short_name == alt and any(f"{alt}.csv?" in c for c in calls)
    with pytest.raises(UpstreamError):
        fetch(settings, "global_precip", PRECIP, {"type": "Point", "coordinates": [0, 0]}, [],
              offline=(CAT["global_precip"]["dataset_id"],))
