#!/usr/bin/env python3
"""Build data/catalog_built.json from the OFFICIAL listing endpoints (architecture rule:
"catalog entries come only from the official listing endpoints; no hand-typed data").

* Giovanni /configured-variables  -> which seed IDs are live (verified=true/false) + every
                                     other configured variable as an extra catalog entry
* CMR collections / variables      -> coverage start, collection title, units, long names
* AppEEARS /product + /product/{id}-> product exists, layer exists, official units

The seed file keeps the editorial plain-language definitions; this script only overrides
facts (units, coverage, verification) and adds variables without editorial text.

    python scripts/build_catalog.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.catalog.catalog import load_catalog  # noqa: E402
from backend.connectors.cmr import CMR  # noqa: E402
from backend.core.config import get_settings  # noqa: E402
from backend.core.http import ResilientHTTP  # noqa: E402
from backend.timeseries.parsers import parse_configured_variables, split_giovanni_id  # noqa: E402

RES_HINTS = [("M2T1", "hourly"), ("M2TM", "monthly"), ("_3H", "3-hourly"), ("_M", "monthly"), ("IMERGM", "monthly"),
             ("IMERGDF", "daily"), ("3STD", "daily"), ("3STM", "monthly"), ("d_", "daily"), ("_D", "daily")]


def guess_resolution(short: str) -> str:
    for k, v in RES_HINTS:
        if k in short:
            return v
    return "daily"


async def main() -> None:
    s = get_settings()
    http = ResilientHTTP(s)
    cmr = CMR(s.cmr_base, http)
    cat = load_catalog()          # seed only
    updates: dict[str, dict] = {}
    additional: list[dict] = []
    report = {"giovanni": None, "appeears": None, "cmr": 0}

    # ---- Giovanni
    try:
        r = await http.request("GET", f"{s.giovanni_base}/configured-variables/", use_cache=False)
        live = set(parse_configured_variables(r.content))
        report["giovanni"] = len(live)
        seed_ids = {v.get("giovanni_id") for v in cat.variables.values()}
        for vid, v in cat.variables.items():
            if v.get("giovanni_id"):
                updates.setdefault(vid, {})["verified"] = v["giovanni_id"] in live
        for gid in sorted(live - seed_ids):
            p = split_giovanni_id(gid)
            additional.append({
                "id": "gio_" + gid.lower(), "name": f"{p['variable']} ({p['short_name']} v{p['version']})",
                "short_definition": None, "definition": None, "definition_source": "none (official listing only)",
                "keywords": [p["variable"] or "", p["short_name"] or ""], "domain": "atmosphere", "family": "other",
                "source": "giovanni", "verified": True, "giovanni_id": gid, "harmony_variable": gid,
                "dataset": {"short_name": p["short_name"], "version": p["version"], "variable": p["variable"]},
                "fallback": None, "native_resolution": guess_resolution(p["short_name"] or ""),
                "units": None, "spatial_modes": ["point", "area"], "land_only": False,
            })
    except Exception as exc:  # noqa: BLE001
        print("Giovanni listing failed:", exc)

    # ---- CMR enrichment (seed entries)
    for vid, v in cat.variables.items():
        ds = v.get("dataset") or {}
        if not ds.get("short_name") or v.get("source") == "ncei":
            continue
        try:
            col = await cmr.collection(short_name=ds["short_name"], version=ds.get("version"),
                                       concept_id=ds.get("concept_id"))
            if col:
                u = updates.setdefault(vid, {})
                u["dataset"] = {**ds, "concept_id": ds.get("concept_id") or col.get("id"),
                                "title": col.get("title"), "doi": ds.get("doi")}
                if col.get("time_start"):
                    u["coverage_start"] = col["time_start"][:7]
                    u["coverage_source"] = "cmr"
                report["cmr"] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"CMR {vid}: {exc}")

    # ---- AppEEARS
    try:
        r = await http.request("GET", f"{s.appeears_base}/product", use_cache=False)
        prods = {p.get("ProductAndVersion"): p for p in r.json()}
        report["appeears"] = len(prods)
        for vid, v in cat.variables.items():
            if v.get("source") != "appeears":
                continue
            ok = v["product_id"] in prods
            u = updates.setdefault(vid, {})
            u["verified"] = ok
            if ok:
                layers = (await http.request("GET", f"{s.appeears_base}/product/{v['product_id']}")).json()
                lay = layers.get(v["layer"])
                u["verified"] = lay is not None
                if lay and lay.get("Units"):
                    u["units"] = lay["Units"]
                    u["units_source"] = "appeears"
    except Exception as exc:  # noqa: BLE001
        print("AppEEARS listing failed:", exc)

    out = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "report": report,
           "updates": updates, "additional": additional}
    p = s.data_dir / "catalog_built.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    await http.aclose()
    unverified = [k for k, u in updates.items() if u.get("verified") is False]
    print(f"wrote {p}\n report={report}\n extra variables={len(additional)}\n seed entries NOT verified: {unverified}")


if __name__ == "__main__":
    asyncio.run(main())
