"""/api/replication/seawifs: re-run the challenge's SeaWiFS river-outflow paper on the same boxes.

GET  /api/replication/seawifs   -> published table + any cached replication/extension results (instant)
POST /api/replication/seawifs   -> 202 {job_id, status_url}; poll GET /api/jobs/{job_id}; result = same shape as GET
Runs: replication = SeaWiFS 1998-01..2007-12 (paper's sensor and period; MODIS-Aqua 2002-07..2007-12 as a labelled
substitute if SeaWiFS cannot be fetched); extension = MODIS-Aqua 2002-07 to the latest full calendar year.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field

from ..analysis.engine import _clean
from ..core.errors import InvalidRequest
from ..core.geometry import parse_geometry
from ..timeseries.model import utc_now_iso
from .method import agreement, paper_regression
from .paper import BY_ID, EXCLUSIONS, PAPER, RIVERS

router = APIRouter(prefix="/api/replication", tags=["replication"], default_response_class=ORJSONResponse)
RUNS = ("replication", "extension")
_LOCK = threading.Lock()


def run_specs(today: date | None = None) -> dict:
    end_year = (today or date.today()).year - 1
    return {
        "replication": [
            {"variable": "seawifs_chlorophyll", "start": date(1998, 1, 1), "end": date(2007, 12, 31),
             "label": "SeaWiFS, 1998-2007 (the paper's sensor and period)", "substitute": False},
            {"variable": "modis_chlorophyll", "start": date(2002, 7, 1), "end": date(2007, 12, 31),
             "label": "MODIS-Aqua, 2002-07 to 2007-12 (substitute: SeaWiFS could not be fetched)", "substitute": True},
        ],
        "extension": [
            {"variable": "modis_chlorophyll", "start": date(2002, 7, 1), "end": date(end_year, 12, 31),
             "label": f"MODIS-Aqua, 2002-07 to {end_year}-12 (extension to the latest full year)",
             "substitute": False},
        ],
    }


def _cache_path(st):
    return st.settings.data_dir / "replication_seawifs.json"


def load_cache(st) -> dict:
    p = _cache_path(st)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"rivers": {}, "updated_at": None}


def save_cache(st, cache: dict) -> None:
    with _LOCK:
        _cache_path(st).write_text(json.dumps(cache, default=str), encoding="utf-8")


async def run_one(st, river: dict, run: str, refresh: bool = False) -> dict:
    """Fetch the box's monthly chl a through the time-series service and apply the paper's method."""
    region = parse_geometry({"type": "BBox", "bbox": river["bbox"], "name": f"{river['name']} outflow box"})
    attempts = []
    for spec in run_specs()[run]:
        try:
            info = await st.ts.build_series(spec["variable"], region, spec["start"], spec["end"], refresh=refresh)
        except Exception as exc:  # noqa: BLE001 - try the next dataset, record why
            attempts.append({"variable": spec["variable"], "error": getattr(exc, "message", str(exc))})
            continue
        ms = st.store.load(info["series_id"])
        res = paper_regression(ms.time, ms.value)
        out = {**res, "dataset": spec["label"], "variable": spec["variable"], "substitute": spec["substitute"],
               "series_id": info["series_id"], "provenance": ms.provenance.to_dict(), "attempts": attempts,
               "area_mean_note": "cos(latitude)-weighted mean of the valid ~0.083 deg cells in the 0.5 deg box "
                                 "(over 0.5 deg the weights differ by <1%, so this matches the paper's arithmetic mean)"}
        ex = EXCLUSIONS.get(river["id"])
        if ex:
            out["variant"] = {**paper_regression(ms.time, ms.value, exclude=ex), "label": ex["label"]}
            out["variant"].pop("series", None)
        return out
    return {"status": "error", "message": "; ".join(a["error"] for a in attempts) or "no dataset", "attempts": attempts}


def summarize(rows: list[dict]) -> str:
    done = [r for r in rows if r["agreement"]["label"] != "Not enough data"]
    if not done:
        return ("No replication has been run yet. The published table is shown; press 'Run the replication' to "
                "re-compute it from NASA satellite data.")
    cons = [r["name"] for r in done if r["agreement"]["label"] == "Consistent"]
    neg = [r["name"] for r in done if r["replication"]["monthly"]["significant"]
           and r["replication"]["monthly"]["slope_per_month"] < 0]
    pos = [r["name"] for r in done if r["replication"]["monthly"]["significant"]
           and r["replication"]["monthly"]["slope_per_month"] > 0]
    sub = any(r["replication"].get("substitute") for r in done)
    s = (f"Our replication is consistent with the published result for {len(cons)} of {len(done)} river boxes "
         f"(same significance call at p < 0.05 and, where the paper's trend is significant, the same direction)"
         + (" - some boxes used MODIS-Aqua as a substitute for SeaWiFS" if sub else "") + ". ")
    s += (f"Significant negative trends in our replication: {', '.join(neg) or 'none'}; "
          f"significant positive: {', '.join(pos) or 'none'}. ")
    s += PAPER["conclusion"]
    return s


def assemble(cache: dict) -> dict:
    rows = []
    for r in RIVERS:
        c = cache.get("rivers", {}).get(r["id"], {})
        rep, ext = c.get("replication"), c.get("extension")
        rows.append({**r, "replication": rep, "extension": ext, "agreement": agreement(r["published"], rep),
                     "extension_agreement": agreement(r["published"], ext)})
    return _clean({"paper": PAPER, "rivers": rows, "summary": summarize(rows), "updated_at": cache.get("updated_at"),
                   "cached": bool(cache.get("rivers")),
                   "notes": [PAPER["caveat"],
                             "The paper's F-test treats each month as independent. Our app's default test also "
                             "corrects for month-to-month persistence (p_persistence_corrected), which usually gives "
                             "a larger p-value.",
                             "Trends are statistical associations; the paper associates them with river discharge, "
                             "dams and nutrient loads, and this replication does not test causes."]})


class ReplicationRequest(BaseModel):
    rivers: list[str] | None = Field(None, max_length=10, description="river ids (default: all 10)")
    runs: list[str] | None = Field(None, max_length=2, description="'replication' and/or 'extension' (default both)")
    refresh: bool = Field(False, description="re-download the series instead of using cached ones")


def _st(request: Request):
    return request.app.state.etd


@router.get("/seawifs")
async def get_replication(request: Request):
    return assemble(load_cache(_st(request)))


@router.post("/seawifs", status_code=202)
async def start_replication(request: Request, body: ReplicationRequest):
    st = _st(request)
    rivers = body.rivers or [r["id"] for r in RIVERS]
    runs = body.runs or list(RUNS)
    bad = [x for x in rivers if x not in BY_ID] + [x for x in runs if x not in RUNS]
    if bad:
        raise InvalidRequest(f"Unknown river or run: {', '.join(bad)}",
                             detail={"rivers": list(BY_ID), "runs": list(RUNS)})
    tasks = [(rid, run) for rid in rivers for run in runs]

    async def job(progress):
        sem = asyncio.Semaphore(3)
        done = [0]

        async def one(rid, run):
            async with sem:
                res = await run_one(st, BY_ID[rid], run, refresh=body.refresh)
            cache = load_cache(st)                       # merge each result as it lands
            cache["rivers"].setdefault(rid, {})[run] = _clean(res)
            cache["updated_at"] = utc_now_iso()
            save_cache(st, cache)
            done[0] += 1
            await progress(done[0] / len(tasks) * 0.95, f"{BY_ID[rid]['name']} {run}: {res.get('status')} "
                                                       f"({done[0]}/{len(tasks)})")
        await asyncio.gather(*(one(rid, run) for rid, run in tasks))
        return assemble(load_cache(st))

    jid = st.jobs.submit("replication", body.model_dump(), job)
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}", "tasks": len(tasks)}
