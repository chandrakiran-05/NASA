"""Live fan-out for active trends: fetch -> detect -> independent checks -> BEAST -> verdict.

Every variable moves through the pipeline on its own, so results stream while slower sources
(AppEEARS takes minutes) are still downloading. Each step is an event in an EventLog that the API
exposes as long-poll JSON and as Server-Sent Events. Identical requests share one running job, so a
frontend can start a scan speculatively while the student is still typing and pick it up on submit.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict

from statsmodels.stats.multitest import multipletests

from ..catalog.catalog import DATA
from ..core.errors import InvalidRequest
from ..insights.onset import change_onset
from ..novelty.integrity import events_for
from ..novelty.scan import LINKS
from ..novelty.agreement import GROUPS
from ..timeseries.service import parse_date
from . import engine

CRITERIA = json.loads((DATA / "criteria.json").read_text(encoding="utf-8"))["criteria"]
FETCH_CONCURRENCY = 4
REVIEW_CONCERNS = ["short_record", "instrument_change", "single_extreme_event", "seasonal_artifact",
                   "land_use_change", "model_not_observation", "region_too_small", "none"]


class EventLog:
    def __init__(self):
        self.events: list[dict] = []
        self.done = False
        self._cond = asyncio.Condition()

    async def emit(self, kind: str, **payload) -> None:
        async with self._cond:
            self.events.append({"seq": len(self.events), "type": kind, "t": round(time.time(), 3), **payload})
            self.done = self.done or kind in ("done", "error")
            self._cond.notify_all()

    async def wait(self, after: int, timeout: float) -> list[dict]:
        async with self._cond:
            if len(self.events) <= after and not self.done:
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
            return self.events[after:]


LOGS: OrderedDict[str, EventLog] = OrderedDict()     # job_id -> log (in memory; the final result is in the DB)
INFLIGHT: dict[str, str] = {}                        # request hash -> job_id


def register(job_id: str, log: EventLog, max_logs: int = 100) -> None:
    LOGS[job_id] = log
    while len(LOGS) > max_logs:
        LOGS.popitem(last=False)


# ------------------------------------------------------------------ criteria
def criteria_view(catalog) -> list[dict]:
    out = []
    for c in CRITERIA:
        have = [v for v in c["variables"] if v in catalog.variables]
        out.append({**c, "variables": [{"id": v, "name": catalog.variables[v]["name"],
                                        "short_definition": catalog.variables[v].get("short_definition")}
                                       for v in have],
                    "missing_variables": [v for v in c["variables"] if v not in have]})
    return out


def plan(catalog, region, start, end, *, criteria: list[str] | None, variable_ids: list[str] | None,
         per_criterion: int, options: dict) -> tuple[list[dict], list[dict]]:
    """-> (items [{variable_id, criteria}], skipped [{variable_id|criterion, reason}])"""
    by_id = {c["id"]: c for c in CRITERIA}
    unknown = [c for c in criteria or [] if c not in by_id]
    if unknown:
        raise InvalidRequest(f"Unknown criteria {unknown}; see GET /api/criteria")
    items: dict[str, list[str]] = {}
    skipped = []
    if variable_ids:
        for v in variable_ids:
            catalog.get(v)
            items[v] = [c["id"] for c in CRITERIA if v in c["variables"]]
        chosen = []
    else:
        chosen = [by_id[c] for c in criteria] if criteria else [c for c in CRITERIA if c["status"] != "not_trendable"]
    for c in chosen:
        if c["status"] == "not_trendable":
            skipped.append({"criterion": c["id"], "reason": c["note"], "where_to_look": c.get("where_to_look", [])})
            continue
        taken = 0
        for v in c["variables"]:
            if taken >= per_criterion:
                break
            why = _ineligible(catalog.variables.get(v), region, start, end, options)
            if why:
                skipped.append({"criterion": c["id"], "variable_id": v, "reason": why})
                continue
            items.setdefault(v, []).append(c["id"])
            taken += 1
    return [{"variable_id": v, "criteria": cs} for v, cs in items.items()], skipped


def _ineligible(v: dict | None, region, start, end, options: dict) -> str | None:
    if v is None:
        return "not in the catalog yet"
    if v.get("requires_option") and v["requires_option"] not in options:
        return f"needs options.{v['requires_option']}"
    mode = "point" if region.is_point else "area"
    if mode not in v.get("spatial_modes", [mode]):
        return f"available only for {', '.join(v.get('spatial_modes', []))}"
    first = max(start.year, int(v["coverage_start"][:4])) if v.get("coverage_start") else start.year
    if end.year - first + 1 < engine.MIN_YEARS:
        return (f"record starts {v.get('coverage_start')}; active-trend detection needs {engine.MIN_YEARS} years "
                f"in the chosen period")
    return None


# ------------------------------------------------------------------ the job
async def run(st, log: EventLog, progress, *, items: list[dict], region, start, end, alpha: float,
              ai_review: bool, options: dict) -> dict:
    from ..api import pipeline
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    total = max(len(items), 1)
    finished = 0
    dets, sids, checks, beasts, failed = {}, {}, {}, {}, {}

    async def novelty(kind, sid, fn, params):
        return await pipeline.cached_novelty(st, kind, sid, fn, {"alpha": alpha, **params})

    async def one(it):
        nonlocal finished
        key = it["variable_id"] or it["series_id"]
        try:
            sid = it.get("series_id")
            if sid is None:
                async with sem:
                    await log.emit("fetching", variable_id=key)
                    info = await st.ts.build_series(key, region, start, end, options=options)
                sid = info["series_id"]
                await log.emit("fetched", variable_id=key, series_id=sid, cached=info.get("cached"),
                               completeness=info.get("completeness"))
            sids[key] = sid
            det = await novelty("active_detect", sid, lambda ms: engine.detect(ms, alpha), {})
            dets[key] = det
            await log.emit("candidate" if det["active"] else "not_active", variable_id=key, series_id=sid,
                           state=det["state"], plain_language=det["plain_language"],
                           rate_per_decade=det.get("rate_per_decade"), units=det.get("units"))
            if not det["active"]:
                return
            W = {"w": det["window_years"]}
            jobs = {
                "integrity": novelty("active_integrity", sid, lambda ms: engine.check_integrity(ms, det), W),
                "court": novelty("active_court", sid, lambda ms: engine.check_court(ms, det, alpha), W),
                "chance": novelty("active_chance", sid, lambda ms: engine.check_chance(ms, det, alpha), W),
                "stability": novelty("active_stability", sid, lambda ms: engine.check_stability(ms, det, alpha), W),
            }
            checks[key] = []
            for fut in asyncio.as_completed([asyncio.ensure_future(j) for j in jobs.values()]):
                c = await fut
                checks[key].append(c)
                await log.emit("check", variable_id=key, **c)
            if any(c["status"] == "fail" for c in checks[key]):
                beasts[key] = {"status": "skipped", "agrees": None,
                               "plain_language": "BEAST not run: an earlier check failed."}
            else:
                await log.emit("beast_started", variable_id=key)
                onset = await pipeline.cached_novelty(
                    st, "onset", sid, lambda ms: change_onset(ms, seams=events_for(ms), alpha=alpha, n_surrogates=49),
                    {"alpha": alpha, "k": 49})
                beasts[key] = engine.beast_gate(onset, det)
            await log.emit("beast", variable_id=key, **beasts[key])
            await log.emit("verdict", variable_id=key, provisional=True, **engine.label(det, checks[key], beasts[key]))
        except Exception as exc:  # noqa: BLE001 - one failing variable must not sink the scan
            failed[key] = getattr(exc, "message", str(exc))
            await log.emit("failed", variable_id=key, message=failed[key])
        finally:
            finished += 1
            await progress(0.9 * finished / total, f"{finished} of {total} variables done")

    await log.emit("started", variables=[i["variable_id"] or i["series_id"] for i in items])
    await asyncio.gather(*(one(it) for it in items))

    # ---- cross-variable checks need every detection
    ok = {k: d for k, d in dets.items() if d["state"] != "too_short"}
    q = {}
    if ok:
        keys = list(ok)
        _, qs, _, _ = multipletests([ok[k]["recent"]["p"] for k in keys], alpha=alpha, method="fdr_bh")
        q = dict(zip(keys, map(float, qs)))
    trends = []
    for key in checks:
        det = dets[key]
        extra = [engine.check_physics(key, ok, LINKS), engine.check_second_opinion(key, ok, GROUPS),
                 engine.make_check("fdr", "pass" if q.get(key, 1) < alpha else "warn",
                               f"After correcting for testing {len(ok)} variables at once (Benjamini-Hochberg), "
                               f"q = {q.get(key, 1):.3f}.", q=q.get(key))]
        for c in extra:
            if c["status"] != "skipped":
                await log.emit("check", variable_id=key, **c)
        checks[key] += [c for c in extra if c["status"] != "skipped"]
        verdict = engine.label(det, checks[key], beasts.get(key))
        await log.emit("verdict", variable_id=key, provisional=False, **verdict)
        v = st.catalog.variables.get(key, {})
        trends.append({"variable_id": key, "name": v.get("name") or key, "series_id": sids[key],
                       "criteria": next((i.get("criteria", []) for i in items if (i["variable_id"] or i["series_id"]) == key), []),
                       "detect": det, "checks": checks[key], "beast": beasts.get(key), "verdict": verdict})

    if ai_review and trends:
        await progress(0.92, "Local AI reviewer")
        for tr in trends:
            if tr["verdict"]["label"] != "NOT VERIFIED":
                tr["ai_review"] = engine.check_llm_note(await review(st.llm, tr))
                await log.emit("check", variable_id=tr["variable_id"], **tr["ai_review"])

    order = {"VERIFIED": 0, "PROBABLE": 1, "NOT VERIFIED": 2}
    trends.sort(key=lambda r: (order[r["verdict"]["label"]], -(r["detect"].get("effect_sd_per_decade") or 0)))
    not_active = [{"variable_id": k, "name": st.catalog.variables.get(k, {}).get("name") or k, "series_id": sids.get(k),
                   "state": d["state"], "plain_language": d["plain_language"]} for k, d in dets.items() if not d["active"]]
    n_ver = sum(t["verdict"]["label"] == "VERIFIED" for t in trends)
    n_prob = sum(t["verdict"]["label"] == "PROBABLE" for t in trends)
    out = {"period": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
           "region": region.as_dict() if region else None,
           "trends": trends, "not_active": not_active, "failed": failed,
           "summary": {"variables": len(items), "active_candidates": len(trends), "verified": n_ver, "probable": n_prob},
           "plain_language": (f"{len(trends)} of {len(dets)} variables are changing now; {n_ver} passed every check "
                              f"and BEAST agrees, {n_prob} are probable."),
           "method": engine.__doc__.split("\n\n")[1].strip(),
           "limits": [engine.LIMIT,
                      "Active means 'detectable in the recent window'; a trend can exist and still be too weak to detect.",
                      "Physics and second-opinion checks compare signs only; they are 'consistent with', never a cause."]}
    await log.emit("done", summary=out["summary"], plain_language=out["plain_language"])
    return out


async def review(llm, tr: dict) -> dict | None:
    """A local LLM (live Ollama tier or deep AirLLM tier) as a skeptical reviewer. Advisory only: it picks concerns from a closed list
    and its note must pass the numeric fact-check, otherwise the note is dropped."""
    from ..ai.verify import verify_text
    d = tr["detect"]
    facts = {"variable": tr["name"], "direction": d["direction"], "significant": True,
             "rate_per_decade": d["rate_per_decade"], "units": d["units"], "window": d["recent_window"],
             "years": [int(d["recent_window"]["start"][:4]), int(d["recent_window"]["end"][:4])],
             "state": d["state"], "checks": {c["check"]: c["status"] for c in tr["checks"]},
             "beast": (tr["beast"] or {}).get("status")}
    schema = {"type": "object", "properties": {
        "concerns": {"type": "array", "items": {"type": "string", "enum": REVIEW_CONCERNS}},
        "note": {"type": "string"}}, "required": ["concerns", "note"]}
    msgs = [{"role": "system", "content": (
                "You are a skeptical Earth-science reviewer. You get FACTS about a trend that statistics already "
                "tested. Do not compute or invent numbers. Pick concerns only from the allowed list and write one "
                "short sentence. Never claim a cause; say 'consistent with'.")},
            {"role": "user", "content": json.dumps(facts)}]
    out = await llm.chat_json(msgs, schema, max_tokens=160)
    if not out:
        return None
    concerns = [c for c in out.get("concerns", []) if c in REVIEW_CONCERNS and c != "none"]
    note = out.get("note") or ""
    if note and not verify_text(note, facts)["passed"]:
        note = ""
    return {"concerns": concerns, "note": note}


def parse_period(start: str | None, end: str | None):
    s = parse_date(start) if start else None
    e = parse_date(end, end=True) if end else None
    return s, e


def request_key(body: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:20]

