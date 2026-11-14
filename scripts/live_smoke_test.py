#!/usr/bin/env python3
"""Live smoke test against the REAL NASA / NOAA services.

Run this on your own machine (with .env credentials) BEFORE the demo:

    python scripts/live_smoke_test.py            # quick: one small request per service
    python scripts/live_smoke_test.py --full     # also runs AppEEARS (~15 min) and a Harmony job

It checks every response-format assumption the connectors make, prints PASS/FAIL per
check, and saves the raw responses to tests/fixtures/recorded/ so they can replace the
synthetic formats in tests/fakes.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.catalog.catalog import load_catalog  # noqa: E402
from backend.connectors.base import FetchRequest  # noqa: E402
from backend.core.auth import credential_status  # noqa: E402
from backend.core.config import get_settings  # noqa: E402
from backend.core.geometry import parse_geometry  # noqa: E402
from backend.core.http import ResilientHTTP  # noqa: E402
from backend.storage.db import Database  # noqa: E402
from backend.storage.series_store import SeriesStore  # noqa: E402
from backend.timeseries.parsers import parse_configured_variables, parse_giovanni_timeseries_csv  # noqa: E402
from backend.timeseries.service import TimeSeriesService  # noqa: E402

REC = ROOT / "tests" / "fixtures" / "recorded"
RESULTS: list[tuple[str, bool, str]] = []
POINT = parse_geometry({"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"})
BOX = parse_geometry({"type": "BBox", "bbox": [79.8, 12.8, 80.4, 13.4], "name": "Chennai box"})


def record(name: str, content: bytes | str) -> None:
    REC.mkdir(parents=True, exist_ok=True)
    p = REC / name
    p.write_bytes(content if isinstance(content, bytes) else content.encode())


async def check(name: str, coro):
    t0 = time.perf_counter()
    try:
        detail = await coro
        RESULTS.append((name, True, f"{detail} ({time.perf_counter() - t0:.1f}s)"))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((name, False, f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"))
        traceback.print_exc(limit=2)


async def main(full: bool) -> int:
    s = get_settings()
    print("credentials:", credential_status(s))
    http = ResilientHTTP(s)
    cat = load_catalog(s.data_dir)
    svc = TimeSeriesService(s, http, cat, SeriesStore(s.series_dir, Database(s.db_path)))
    gio = svc.connectors["giovanni_point"]

    async def giovanni_list():
        r = await http.request("GET", f"{s.giovanni_base}/configured-variables/", use_cache=False)
        record("giovanni_configured_variables.json", r.content)
        ids = parse_configured_variables(r.content)
        assert len(ids) > 100, f"only {len(ids)} ids parsed - listing format changed?"
        missing = [v["giovanni_id"] for v in cat.variables.values() if v.get("giovanni_id") and v["giovanni_id"] not in ids]
        return f"{len(ids)} ids; seed ids not listed: {missing or 'none'}"

    async def giovanni_point():
        from backend.core.auth import edl_bearer_headers
        params = {"data": "GPM_3IMERGM_07_precipitation", "location": "[13.08,80.27]",
                  "time": "2015-01-01T00:00:00/2016-12-31T23:59:59"}
        r = await http.request("GET", f"{s.giovanni_base}/timeseries", params=params,
                               headers=edl_bearer_headers(s), use_cache=False)
        record("giovanni_timeseries_imergm.csv", r.content)
        hdr, t, v = parse_giovanni_timeseries_csv(r.text)
        assert len(t) == 24, f"expected 24 monthly rows, got {len(t)}"
        assert "unit" in hdr or "units" in hdr, f"no unit in header keys {list(hdr)[:15]}"
        return f"24 rows, unit={hdr.get('unit') or hdr.get('units')}, header keys={list(hdr)[:8]}"

    async def giovanni_quota():
        q = await gio.quota()
        record("giovanni_quota.json", json.dumps(q))
        return f"quota: {q}"

    async def cmr_granules():
        g = await svc.connectors["opendap"].cmr.granules("C1276812859-GES_DISC", date(2020, 1, 1), date(2020, 3, 31))
        record("cmr_granules_m2tmnxslv.json", json.dumps(g[:3]))
        assert len(g) == 3, f"expected 3 monthly granules, got {len(g)}"
        assert ":" in g[0]["title"], f"granule title has no 'ShortName.ver:file' form: {g[0]['title']}"
        return f"titles like {g[0]['title']}"

    async def opendap_area():
        v = cat.get("merra2_t2m")
        raw = await svc.connectors["opendap"].fetch(FetchRequest(v, BOX, date(2020, 1, 1), date(2020, 3, 31)))
        assert len(raw.value) == 3 and all(200 < x < 330 for x in raw.value), raw.value
        return f"T2M box mean {raw.value.round(2).tolist()} {raw.meta.units}"

    async def ncei_ads():
        conn = svc.connectors["ncei"]
        r, (t, v, st) = await conn._ads("global-summary-of-the-month", ["USW00094728"], "TAVG",
                                        date(2019, 1, 1), date(2019, 12, 31))
        record("ncei_ads_gsom.json", r.content)
        assert len(t) >= 10, f"{len(t)} rows"
        return f"{len(t)} rows, first {v[:3].tolist()}"

    async def cdo_stations():
        if not s.noaa_cdo_token:
            return "skipped (no NOAA_CDO_TOKEN)"
        st = await svc.connectors["ncei"].find_stations(POINT, "TAVG", date(2000, 1, 1), date(2020, 12, 31))
        record("cdo_stations.json", json.dumps(st[:5]))
        return f"{len(st)} stations near Chennai; nearest {st[0]['id'] if st else None}"

    async def appeears_product():
        conn = svc.connectors["appeears"]
        meta = await conn.layer_meta("MOD13A3.061")
        record("appeears_product_mod13a3.json", json.dumps(meta))
        vm = conn.value_meta(meta, "_1_km_monthly_NDVI", None)
        assert vm.scale_factor and vm.fill_values, vm
        return f"NDVI fill={vm.fill_values} scale={vm.scale_factor} valid=[{vm.valid_min},{vm.valid_max}]"

    await check("Giovanni /configured-variables", giovanni_list())
    await check("Giovanni /timeseries (point, IMERG monthly)", giovanni_point())
    await check("Giovanni /quota", giovanni_quota())
    await check("CMR granules (M2TMNXSLV)", cmr_granules())
    await check("Cloud OPeNDAP subset + area mean", opendap_area())
    await check("NCEI Access Data Service", ncei_ads())
    await check("CDO v2 /stations", cdo_stations())
    await check("AppEEARS /product layer metadata", appeears_product())

    if full:
        async def harmony():
            v = cat.get("imerg_precip_monthly")
            raw = await svc.connectors["harmony_area"].fetch(FetchRequest(v, BOX, date(2019, 1, 1), date(2019, 12, 31)))
            assert len(raw.value) == 12, len(raw.value)
            return f"12 monthly area means, units={raw.meta.units}"

        async def appeears_point():
            v = cat.get("modis_ndvi_monthly")
            out = await svc.build_series(v["id"], POINT, date(2019, 1, 1), date(2020, 12, 31))
            return f"series {out['series_id']} qc={out['qc']}"

        await check("Harmony area average (IMERG monthly, 2019)", harmony())
        await check("AppEEARS point task (MOD13A3, 2 years) ~15 min", appeears_point())

    await http.aclose()
    print("\n" + "=" * 100)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name:48s} {detail}")
    print("=" * 100)
    print(f"recorded responses in {REC}")
    return 0 if all(ok for _, ok, _ in RESULTS) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="also run Harmony and AppEEARS jobs (slow)")
    sys.exit(asyncio.run(main(ap.parse_args().full)))
