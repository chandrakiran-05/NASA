"""Map a harness config onto the existing model clients, and probe whether a model is good enough.

The probe is the harness gate: the model gets a small FACTS object and must write two sentences that pass
`verify_text` (numbers traced, direction, significance, no causal words, no predictions). A model that
answers but invents a number fails.
"""
from __future__ import annotations

import json
import time

import httpx

from ..ai.deep_llm import DeepLLM
from ..ai.llm import LocalLLM
from ..ai.prompts import SYSTEM_BASE
from ..ai.verify import verify_text
from ..core.config import Settings

PROBE_FACTS = {"region": "Testland", "variable": "near-surface air temperature", "units": "°C",
               "start_year": 1995, "end_year": 2024, "direction": "rising", "rate_per_decade": 0.27,
               "total_change": 0.78, "significant": True, "p_value": 0.003}
PROBE_INSTRUCTIONS = ("Write exactly 2 short sentences for a student that state the trend in FACTS: the "
                      "direction, the rate per decade with units, the period, and whether it is statistically "
                      "significant. Use ONLY numbers in FACTS. No causes, no predictions, no markdown.")


def clients(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> tuple[LocalLLM, DeepLLM]:
    """The live and deep clients for these settings (see config.to_settings), unchanged."""
    return LocalLLM(settings, transport=transport), DeepLLM(settings)


def _messages() -> list[dict]:
    return [{"role": "system", "content": SYSTEM_BASE + "\n" + PROBE_INSTRUCTIONS},
            {"role": "user", "content": "FACTS:\n" + json.dumps(PROBE_FACTS, ensure_ascii=False)}]


async def probe(llm: LocalLLM | DeepLLM) -> dict:
    """Does the model answer, how fast, and does its answer survive the number check?"""
    deep = isinstance(llm, DeepLLM)
    status = await (llm.status() if deep else llm.status(force=True))
    out = {"tier": "deep" if deep else "live", "provider": llm.provider, "model": status.get("model"),
           "available": bool(status.get("available")), "facts": PROBE_FACTS}
    if not status.get("available"):
        return {**out, "verdict": "unavailable",
                "reason": status.get("reason") or status.get("hint") or "model not available"}
    t0 = time.perf_counter()
    if deep:
        obj = await llm.chat_json(_messages(), {"type": "object", "properties": {"text": {"type": "string"}},
                                                "required": ["text"]})
        text = (obj or {}).get("text")
    else:
        text = await llm.chat(_messages(), max_tokens=200)
    dt = time.perf_counter() - t0
    text = (text or "").strip()
    out.update(latency_s=round(dt, 2), answer=text)
    if not text:
        return {**out, "verdict": "fail", "reason": getattr(llm, "last_error", None) or "the model returned no text"}
    # shortcut: ~4 characters per token (client returns text only); measure with the runtime's own stats if needed
    out["approx_tokens_per_s"] = round(len(text) / 4 / dt, 1) if dt > 0 else None
    v = verify_text(text, PROBE_FACTS)
    out["verify"] = {"passed": v["passed"], "badge": v["badge"], "checks": v["checks"],
                     "unsupported_numbers": v["unsupported_numbers"]}
    out["verdict"] = "pass" if v["passed"] else "fail"
    if not v["passed"]:
        out["reason"] = "the answer did not pass the number check: " + v["badge"]
    return out
