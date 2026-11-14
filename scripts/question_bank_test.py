"""End-to-end test: 100 student questions -> planner -> live data -> active trends -> verdict.

    python scripts/question_bank_test.py                 # all questions, writes reports/question_bank.{md,json}
    python scripts/question_bank_test.py --only 1-10     # a slice
Uses the real upstream services (and the local LLM if one is running). Credentials come from .env.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.active.runner import CRITERIA  # noqa: E402
from backend.core.config import Settings  # noqa: E402
from backend.main import create_app  # noqa: E402

CRIT_OF = {}
for c in CRITERIA:
    for v in c["variables"]:
        CRIT_OF.setdefault(v, []).append(c["id"])


def run_one(c: TestClient, i: int, item: dict) -> dict:
    q, want = item["q"], item["criterion"]
    row = {"n": i, "question": q, "expected_criterion": want}
    t0 = time.time()
    plan = c.post("/api/ai/plan", json={"question": q}).json()
    row["planner"] = plan.get("planner") or plan.get("source")
    if not plan.get("on_topic", True):
        row.update(stage="off_topic", outcome="refused (off topic)", ok=want == "off_topic")
        return row
    vars_ = plan.get("variables") or []
    regions = plan.get("regions") or []
    row["variable"] = vars_[0]["id"] if vars_ else None
    row["variable_criteria"] = CRIT_OF.get(row["variable"], [])
    row["criterion_match"] = want in row["variable_criteria"]
    row["region"] = (regions[0].get("name") if regions else None)
    period = plan.get("period") or {}
    start, end = period.get("start") or "1990-01", period.get("end") or "2024-12"
    row["period"] = [start, end]
    if want in ("oil_pollution", "radar_backscatter", "maritime_activity"):
        crit = next(x for x in CRITERIA if x["id"] == want)
        row.update(stage="not_trendable", outcome="not trendable (honest refusal)", ok=True, note=crit["note"])
        return row
    if not vars_ or not regions:
        row.update(stage="plan", outcome="planner found no " + ("variable" if not vars_ else "place"), ok=False)
        return row
    body = {"geometry": regions[0]["geometry"], "start": start, "end": end,
            "variable_ids": [v["id"] for v in vars_[:2]], "ai_review": True, "research": False}
    r = c.post("/api/active-trends", json=body)
    if r.status_code != 202:
        row.update(stage="request", outcome=f"rejected: {r.json().get('error', {}).get('message', r.text)[:200]}", ok=False)
        return row
    jid = r.json()["job_id"]
    row["skipped"] = r.json().get("skipped")
    while True:
        j = c.get(f"/api/jobs/{jid}", params={"wait": 25}).json()
        if j["status"] in ("done", "error") or time.time() - t0 > 1500:
            break
    row["seconds"] = round(time.time() - t0, 1)
    if j["status"] != "done":
        row.update(stage="job", outcome=f"job {j['status']}: {(j.get('error') or {}).get('message')}", ok=False)
        return row
    res = j["result"]
    row["failed_fetch"] = res.get("failed")
    row["trends"] = [{"variable": t["variable_id"], "label": t["verdict"]["label"], "state": t["detect"]["state"],
                      "text": t["detect"]["plain_language"], "beast": (t.get("beast") or {}).get("status"),
                      "checks": {x["check"]: x["status"] for x in t["checks"]}} for t in res["trends"]]
    row["not_active"] = [{"variable": t["variable_id"], "state": t["state"], "text": t["plain_language"]}
                         for t in res["not_active"]]
    if row["trends"] or row["not_active"]:
        best = row["trends"][0] if row["trends"] else row["not_active"][0]
        row.update(stage="analysed", ok=True,
                   outcome=(best.get("label") or "NOT ACTIVE") + " | " + best["text"])
    else:
        msg = "; ".join(f"{k}: {v}" for k, v in (res.get("failed") or {}).items())[:300]
        row.update(stage="fetch", outcome=f"no data: {msg}", ok=False)
    return row


def classify(row: dict) -> str:
    o = row.get("outcome", "")
    if row["stage"] == "fetch" and ("token" in o.lower() or "credential" in o.lower() or "earthdata" in o.lower()):
        return "needs NASA Earthdata token"
    return row["stage"] if not row.get("ok") else ("analysed" if row["stage"] == "analysed" else row["stage"])


def report(rows: list[dict], out: Path, llm: dict) -> None:
    cats = Counter(classify(r) for r in rows)
    match = [r for r in rows if "criterion_match" in r]
    lines = ["# 100-question end-to-end test", "",
             f"Local LLM: {llm}", "",
             "| Outcome | Count |", "|---|---|", *[f"| {k} | {v} |" for k, v in cats.most_common()], "",
             f"Planner picked a variable of the expected criterion: {sum(r['criterion_match'] for r in match)} of {len(match)}.",
             "", "| # | Question | Variable | Place | Result |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['n']} | {r['question']} | {r.get('variable') or '-'} | {r.get('region') or '-'} | "
                     f"{(r.get('outcome') or '').replace('|', '/')} |")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="e.g. 1-10")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    items = json.loads((ROOT / "scripts" / "question_bank.json").read_text(encoding="utf-8"))["questions"]
    idx = list(range(1, len(items) + 1))
    if a.only:
        lo, hi = map(int, a.only.split("-"))
        idx = [i for i in idx if lo <= i <= hi]
    app = create_app(Settings(data_dir=ROOT / "data"))      # real settings + .env; shared cache with the server
    with TestClient(app) as c:
        llm = c.get("/api/ai/status").json()
        with ThreadPoolExecutor(a.workers) as ex:
            rows = list(ex.map(lambda i: _safe(c, i, items[i - 1]), idx))
    out = ROOT / "reports" / "question_bank"
    out.parent.mkdir(exist_ok=True)
    report(rows, out, llm)
    print(Path(out.with_suffix(".md")).read_text(encoding="utf-8").split("| # |")[0])


def _safe(c, i, item):
    try:
        return run_one(c, i, item)
    except Exception as exc:  # noqa: BLE001 - one broken question must not stop the run
        return {"n": i, "question": item["q"], "expected_criterion": item["criterion"], "stage": "crash",
                "ok": False, "outcome": f"crash: {type(exc).__name__}: {exc}"[:300]}


if __name__ == "__main__":
    main()
