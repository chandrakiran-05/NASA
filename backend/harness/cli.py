"""trend-harness: install our pipeline, plug in your own local model.

  trend-harness init                write a commented harness.toml (detects Ollama / LM Studio / llama.cpp)
  trend-harness doctor              config + model probe + data credentials + BEAST check
  trend-harness ask "question"      run the real report pipeline in-process (--json for machines)
  trend-harness serve               start the API with the harness config applied

Same as `python -m backend.harness ...`.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path

import httpx

from . import config as hc

RUNTIMES = [  # (name, provider, base_url, probe path)
    ("Ollama", "ollama", "http://127.0.0.1:11434", "/api/tags"),
    ("LM Studio", "openai-compatible", "http://127.0.0.1:1234", "/v1/models"),
    ("llama.cpp server", "openai-compatible", "http://127.0.0.1:8080", "/v1/models"),
]


def _out(*a) -> None:
    print(*a, flush=True)


def detect_runtimes() -> list[dict]:
    found = []
    for name, prov, url, path in RUNTIMES:
        try:
            r = httpx.get(url + path, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name") or m.get("id") for m in data.get("models") or data.get("data") or []]
                found.append({"name": name, "provider": prov, "base_url": url, "models": [m for m in models if m]})
        except (httpx.HTTPError, ValueError):
            continue
    return found


# ---------------------------------------------------------------- init
def cmd_init(a) -> int:
    from ..core import hardware
    path = Path(a.config or hc.DEFAULT_PATH)
    if path.exists() and not a.force:
        _out(f"{path} already exists (use --force to overwrite)")
        return 1
    rec = hardware.recommend(hardware.probe())
    want = rec["live"]["model"]
    _out(f"Recommended live model for this machine: {want} ({rec['live']['why']})")
    for n in rec["notes"]:
        _out(f"  note: {n}")
    found = detect_runtimes()
    rt = next(iter(found), None)
    if rt:
        _out(f"Found {rt['name']} at {rt['base_url']} with {len(rt['models'])} model(s)")
        name = want if want in rt["models"] or rt["provider"] == "ollama" else (rt["models"] or [want])[0]
        provider, base = rt["provider"], rt["base_url"]
    else:
        _out(f"No local model server found on the default ports. Install Ollama, then: ollama pull {want}")
        provider, base, name = "ollama", "http://127.0.0.1:11434", want
    path.write_text(hc.TEMPLATE.format(provider=provider, base_url=base, name=name), encoding="utf-8")
    _out(f"Wrote {path}. Next: trend-harness doctor")
    return 0


# ---------------------------------------------------------------- doctor
def _load(a):
    try:
        cfg, path = hc.load(a.config)
    except hc.HarnessConfigError as exc:
        _out(f"[FAIL] config: {exc}")
        return None, None, None
    return cfg, path, hc.to_settings(cfg)


def beast_check() -> dict:
    try:
        mod = importlib.import_module("Rbeast")
        return {"ok": True, "version": getattr(mod, "__version__", "installed")}
    except Exception as exc:  # noqa: BLE001 - report any import failure
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc} (pip install Rbeast)"}


async def _doctor_probe(settings, deep: bool) -> list[dict]:
    from .models import clients, probe
    live, dl = clients(settings)
    try:
        out = [await probe(live)]
        if deep and dl.enabled:
            out.append(await probe(dl))
        return out
    finally:
        await live.aclose()
        await dl.aclose()


def cmd_doctor(a) -> int:
    from ..core.auth import credential_status
    cfg, path, s = _load(a)
    if cfg is None:
        return 1
    _out(f"[ OK ] config: {path or 'defaults (no harness.toml; run trend-harness init)'}")
    m = cfg.model
    _out(f"       model: {m.provider} {m.name} at {hc.public_url(m.base_url)}; deep: {cfg.deep.provider}")
    p = cfg.pipeline
    _out(f"       pipeline: alpha={p.alpha} min_years={p.min_years} verify={p.verify} rewrite={p.rewrite} "
         f"sections={p.rewrite_sections if p.rewrite else []}")
    rc = 0
    for r in asyncio.run(_doctor_probe(s, a.deep)):
        tag = {"pass": "[ OK ]", "fail": "[FAIL]"}.get(r["verdict"], "[WARN]")
        rc = 2 if r["verdict"] == "fail" else rc
        _out(f"{tag} {r['tier']} model {r.get('model') or ''}: {r['verdict']}"
             + (f", {r['latency_s']} s, ~{r.get('approx_tokens_per_s')} tok/s" if "latency_s" in r else "")
             + (f" - {r['reason']}" if r.get("reason") else ""))
        if r.get("verify"):
            _out(f"       number check: {r['verify']['badge']}")
        if r.get("answer"):
            _out(f"       answer: {r['answer'][:300]}")
    creds = credential_status(s)
    _out("[INFO] data credentials (values never shown): "
         + ", ".join(f"{k}={'set' if v else 'missing'}" for k, v in creds.items()))
    if not any(creds.values()):
        _out("       keyless sources (NOAA ERDDAP etc.) still work; NASA Giovanni/AppEEARS need Earthdata login")
    b = beast_check()
    _out(f"[{' OK ' if b['ok'] else 'FAIL'}] BEAST (Rbeast): {b.get('version') or b.get('reason')}")
    return rc or (0 if b["ok"] else 2)


# ---------------------------------------------------------------- ask
async def run_report(settings, question: str, alpha: float, progress=None) -> dict:
    """The real report pipeline, in-process (same code as POST /api/report)."""
    from ..main import build_state
    from ..report import build_report
    st = build_state(settings)
    try:
        return await build_report(st, question=question, alpha=alpha, progress=progress)
    finally:
        await st.jobs.shutdown()
        await st.http.aclose()
        await st.llm.aclose()
        await st.deep.aclose()
        st.db.close()


def summarize(rep: dict) -> dict:
    secs = {s["id"]: s for s in rep.get("sections") or []}
    ans, real = secs.get("answer") or {}, (secs.get("is_it_real") or {}).get("data") or {}
    prov = rep.get("provenance") or {}
    return {"question": rep.get("question"), "headline": rep.get("headline"),
            "answer": ans.get("text"), "answer_source": ans.get("text_source"),
            "verdict": {"active_trend_label": real.get("verdict"), "court_stamp": (real.get("court") or {}).get("stamp"),
                        "limit": real.get("limit")},
            "numbers_from": {"engine": "backend/analysis + backend/active (trend tests, Trend Court, BEAST + PELT)",
                             "dataset": prov.get("dataset_short_name"), "version": prov.get("version"),
                             "doi": prov.get("doi"), "source_api": prov.get("source_api"),
                             "retrieved_at": prov.get("retrieved_at"), "series_id": prov.get("series_id")},
            "plan": rep.get("plan"), "ai": rep.get("ai"), "limits": rep.get("limits")}


def cmd_ask(a) -> int:
    cfg, _, s = _load(a)
    if cfg is None:
        return 1
    hc.apply_pipeline(cfg)

    async def progress(frac, msg):
        if not a.json:
            print(f"  [{frac:4.0%}] {msg}", file=sys.stderr, flush=True)
    try:
        rep = asyncio.run(run_report(s, a.question, cfg.pipeline.alpha, progress))
    except Exception as exc:  # noqa: BLE001 - show the pipeline's own message
        msg = getattr(exc, "message", None) or str(exc)
        _out(json.dumps({"error": msg}) if a.json else f"error: {msg}")
        return 1
    out = summarize(rep)
    if a.json:
        _out(json.dumps(out, ensure_ascii=False, default=str, indent=2))
        return 0
    v, n = out["verdict"], out["numbers_from"]
    _out(f"\n{out['headline']}\n\n{out['answer']}\n  ({'AI-written, number-checked' if out['answer_source'] == 'local_llm' else 'template text'})")
    _out(f"\nVerdict: court stamp {v['court_stamp'] or '-'}; active-trend label {v['active_trend_label'] or '-'}")
    if v["limit"]:
        _out(f"Limit: {v['limit']}")
    _out(f"Numbers from: {n['engine']}\nData: {n['dataset']} {n['version'] or ''} via {n['source_api']} "
         f"(DOI {n['doi'] or '-'}, retrieved {n['retrieved_at'] or '-'})")
    for lim in out["limits"] or []:
        _out(f"  - {lim}")
    return 0


# ---------------------------------------------------------------- serve
def cmd_serve(a) -> int:
    import uvicorn

    from . import api
    from ..main import create_app
    cfg, path, s = _load(a)
    if cfg is None:
        return 1
    hc.apply_pipeline(cfg)
    api.ACTIVE = {"config": cfg, "path": str(path) if path else None}
    _out(f"Serving with {cfg.model.provider} {cfg.model.name}; API docs at http://{a.host}:{a.port}/docs")
    uvicorn.run(create_app(s), host=a.host, port=a.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trend-harness", description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", help="path to harness.toml (default: ./harness.toml or $TREND_HARNESS_CONFIG)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="write a commented harness.toml")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("doctor", help="check config, model, credentials and BEAST")
    p.add_argument("--deep", action="store_true", help="also probe the AirLLM deep tier (minutes)")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("ask", help="answer one question with the full pipeline")
    p.add_argument("question")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("serve", help="start the API with this config")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):        # Windows consoles default to cp1252; units use °C and ·
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    return a.fn(a)
