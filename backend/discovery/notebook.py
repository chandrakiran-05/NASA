"""Reproducible notebook for one discovery finding (nbformat 4 JSON written by hand; no extra dependency).

The notebook re-fetches the data through this app's own API and re-runs every step: series, active-trend
checks + BEAST, literature, PCMCI+ drivers and the simulated outlook. It never embeds a token.
"""
from __future__ import annotations

import json


def _src(text: str) -> list[str]:
    lines = text.strip("\n").split("\n")
    return [ln + "\n" for ln in lines[:-1]] + [lines[-1]]


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _src(text)}


def _code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": _src(text)}


def build_notebook(brief: dict, api_base: str, job_id: str) -> dict:
    r = brief["reproduce"]
    title = brief["title"]
    flag = (f"**{brief['discovery_label']}.** " + brief["gap"]["rule"]) if brief.get("potential_discovery") else \
        brief["gap"]["plain_language"]
    cells = [
        _md(f"""# {title}

Discovery-mode brief `{brief['finding_id']}` from job `{job_id}` (Earth System Trend Detective).

* Verdict: **{brief['verdict']['label']}** ({brief['verdict']['why']})
* Limit: {brief['verdict']['limit']}
* Gap check: {flag}
* Drivers are *associations* (PCMCI+), consistent with an influence, never a proven cause.
* The outlook is **{brief['outlook'].get('label')}**.

Every step below calls the app's backend API again, so the numbers are recomputed from the source data.
Start the backend first (`uvicorn backend.main:app --port 8000`) and set `API` if it runs elsewhere."""),
        _code(f"""import json, time
import requests

API = {json.dumps(api_base.rstrip('/'))}
SPEC = {json.dumps({k: r[k] for k in ('variable_id', 'geometry', 'start', 'end', 'alpha', 'direction', 'region_name')}, indent=1)}
DRIVER_IDS = {json.dumps(r.get('driver_ids') or [])}

def wait_job(job_id, timeout=1800):
    t0 = time.time()
    while True:
        j = requests.get(f"{{API}}/api/jobs/{{job_id}}", params={{"wait": 10}}).json()
        if j["status"] in ("done", "error") or time.time() - t0 > timeout:
            if j["status"] == "error":
                raise RuntimeError(j["error"])
            return j["result"]"""),
        _md("## 1. Re-fetch the monthly series (official NASA/NOAA source, cached by the backend)"),
        _code("""r = requests.post(f"{API}/api/timeseries", json={"variable_id": SPEC["variable_id"], "geometry": SPEC["geometry"],
                                           "start": SPEC["start"], "end": SPEC["end"]})
r.raise_for_status()
series = wait_job(r.json()["job_id"])
SID = series["series_id"]
print(SID, series.get("completeness"), series.get("source_api"))"""),
        _md("## 2. Keep what's real: active-trend checks + BEAST verdict"),
        _code("""r = requests.post(f"{API}/api/active-trends", json={"series_ids": [SID], "alpha": SPEC["alpha"],
                                              "ai_review": False, "research": False})
r.raise_for_status()
active = wait_job(r.json()["job_id"])
for t in active["trends"]:
    print(t["verdict"]["label"], "-", t["verdict"]["why"])
    print(t["detect"]["plain_language"])
    print("BEAST:", (t.get("beast") or {}).get("plain_language"))
    print("Limit:", t["verdict"]["limit"])
if not active["trends"]:
    print([n["plain_language"] for n in active["not_active"]])"""),
        _md("## 3. Figure: observed series, trend and the BEAST change date"),
        _code("""import matplotlib.pyplot as plt
import pandas as pd

view = requests.get(f"{API}/api/view/{SID}", params={"explain": "false"}).json()
ch = view["chart"]
t = pd.to_datetime(ch["time"])
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(t, ch["observed"], lw=0.8, color="0.6", label="observed (monthly)")
if ch.get("deseasonalized"):
    ax.plot(t, ch["deseasonalized"], lw=1.0, label="seasonal cycle removed")
if ch.get("sen_line"):
    ax.plot(t, ch["sen_line"], lw=2, label="Sen slope")
for m in view["markers"]:
    if m["kind"] == "beast_confirmed":
        ax.axvline(pd.to_datetime(m["date"]), color="crimson", ls="--", label=f"BEAST change {m['date']}")
ax.set_ylabel(view.get("units") or "")
ax.set_title(view.get("label") or "")
ax.legend(fontsize=8)
plt.show()"""),
        _md("## 4. Check what's known: peer-reviewed literature (abstract keyword reading)"),
        _code("""r = requests.post(f"{API}/api/research/evidence", json={"variable_id": SPEC["variable_id"],
                                                  "direction": SPEC["direction"], "region_name": SPEC["region_name"]})
lit = r.json()
print(lit.get("plain_language"))
for p in lit.get("papers", []):
    print("-", p["year"], p["title"], f"https://doi.org/{p['doi']}" if p.get("doi") else p.get("url"),
          "| peer reviewed" if p.get("peer_reviewed") else "| NOT peer reviewed",
          "| names the place" if p.get("region_match") else "")"""),
        _md("## 5. Drivers: PCMCI+ on candidate driver series for the same box (association only)"),
        _code("""driver_sids = []
for vid in DRIVER_IDS:
    r = requests.post(f"{API}/api/timeseries", json={"variable_id": vid, "geometry": SPEC["geometry"],
                                               "start": SPEC["start"], "end": SPEC["end"]})
    if r.ok:
        try:
            driver_sids.append(wait_job(r.json()["job_id"])["series_id"])
        except RuntimeError as e:
            print("driver", vid, "failed:", e)
if driver_sids:
    d = requests.post(f"{API}/api/drivers", json={"target_series_id": SID, "driver_series_ids": driver_sids,
                                              "method": "pcmci", "max_lag": 3}).json()
    for lk in d.get("best_per_driver", []):
        print(lk["driver"], "lag", lk["lag_months"], "partial r", round(lk["partial_r"], 2),
              "significant" if lk.get("significant") else "not significant")
    print(d.get("disclaimer"))"""),
        _md("## 6. Simulated outlook (digital twin engine): statistical extrapolation, not a prediction"),
        _code("""s = requests.get(f"{API}/api/export/{SID}", params={"format": "json"}).json()
tw = requests.post(f"{API}/api/twin", json={"name": "discovery outlook"}).json()
requests.post(f"{API}/api/twin/{tw['id']}/data", json={"variables": [{
    "name": "target", "time": [x[:7] for x in s["time"]], "value": s["value"],
    "units": view.get("units")}], "source": "discovery notebook"}).raise_for_status()
sim = requests.post(f"{API}/api/twin/{tw['id']}/simulate", json={"horizon_years": 25, "n_runs": 300}).json()
v = sim["variables"]["target"]
print("Simulated 5-95% range at", v["time"][-1], ":", round(v["p05"][-1], 3), "to", round(v["p95"][-1], 3))
print(sim["disclaimer"])"""),
    ]
    return {"cells": cells, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "discovery": {"job_id": job_id, "finding_id": brief["finding_id"], "title": title}},
        "nbformat": 4, "nbformat_minor": 4}
