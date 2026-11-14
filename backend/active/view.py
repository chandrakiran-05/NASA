"""One chart-ready view per series: data + trend lines + BEAST ribbon/events + PELT breaks + the local
model's explanation (fact-checked). Every array is aligned on `time`; gaps stay null. Nothing new is
computed here: it assembles the cached analysis, onset (BEAST) and PELT results."""
from __future__ import annotations


async def build_view(st, series_id: str, *, alpha: float = 0.05, detect: dict | None = None,
                     verdict: dict | None = None, explain: bool = True) -> dict:
    from ..api import pipeline
    from ..insights.onset import change_onset
    from ..novelty.integrity import events_for
    from .runner import _pelt
    analysis = await pipeline.cached_analysis(st, series_id, alpha=alpha)
    onset = await pipeline.cached_novelty(
        st, "onset", series_id, lambda ms: change_onset(ms, seams=events_for(ms), pelt_breaks=_pelt(ms), alpha=alpha,
                                                        n_surrogates=49), {"alpha": alpha, "k": 49, "pelt": True})
    pelt = await pipeline.cached_novelty(st, "pelt", series_id, lambda ms: {"breaks": _pelt(ms)}, {})
    ch = analysis.get("chart") or {}
    ribbon = onset.get("ribbon") or {}
    view = {
        "series_id": series_id, "label": analysis.get("label"), "units": analysis.get("units"),
        "chart": {"time": ch.get("time"), "observed": ch.get("raw"), "deseasonalized": ch.get("deseasonalized"),
                  "sen_line": ch.get("sen_line"), "ols_line": ch.get("ols_line"),
                  "beast_trend": ribbon.get("trend_anomaly"), "change_probability": ribbon.get("change_probability")},
        "markers": [{"date": e["date"], "kind": "beast_" + e["status"], "interval": e.get("interval90"),
                     "probability": e.get("probability"), "agrees_with_pelt": e.get("agrees_with_pelt"),
                     "near_seam": (e.get("near_seam") or {}).get("label")} for e in onset.get("events", [])]
                   + [{"date": b["date"], "kind": "pelt_break"} for b in pelt.get("breaks", [])],
        "segments": onset.get("segments", []),
        "recent_window": (detect or {}).get("recent_window"),
        "verdict": verdict or analysis.get("verdict"),
        "caption": (verdict or {}).get("plain_language") or (analysis.get("verdict") or {}).get("plain_language"),
        "limits": onset.get("limits", []),
    }
    if explain:
        ex = await st.ai.explain(analysis)
        view["explanation"] = {"text": ex["explanation"], "source": ex["source"],
                               "label": "AI-written, number-checked" if ex["source"] == "local_llm" else "template"}
    return view
