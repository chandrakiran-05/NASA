"""Deep-review LLM tier (optional): AirLLM runs a 14B+ model layer by layer from disk.

Same async surface as LocalLLM (`enabled`, `status`, `chat_json`, `aclose`), very different speed:
AirLLM keeps one layer in VRAM and re-reads every layer from disk for every new token, so a 4-bit 14B
model costs a few seconds per token and a 72B model tens of seconds (estimates in core/hardware.py).
Use it only from background jobs, on a few top results, for short JSON answers. Its output is
advisory: it may propose or comment, but deterministic code decides every number and verdict, and any
text it writes must pass the same verifier as the live tier (docs/07-trend-forensics.md §4-5).

Every failure (missing packages, CUDA out of memory, timeout, no JSON) returns None and is logged; nothing
raises into callers. torch/airllm are imported only inside `load_airllm`, which runs in a worker thread.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

from ..core import hardware
from ..core.config import Settings

log = logging.getLogger("etd.deep_llm")

MAX_SEQ_LEN = 2048          # prompt + answer; AirLLM's own default (512) is too short for a FACTS prompt

Generate = Callable[[list[dict], int], str]           # (messages, max_new_tokens) -> generated text
Loader = Callable[[str, Settings], Generate]          # (model id, settings) -> Generate


def _compression(s: Settings) -> str | None:
    c = (s.deep_llm_compression or "").lower()
    return None if c in ("", "none") else c


def load_airllm(model_id: str, s: Settings) -> Generate:
    """Load an AirLLM model (first run downloads it and splits it into per-layer files). Blocking."""
    from airllm import AutoModel                      # imports torch: only here, never at module import

    kw = {"max_seq_len": MAX_SEQ_LEN, "compression": _compression(s)}
    if s.deep_llm_layer_dir:
        kw["layer_shards_saving_path"] = str(s.deep_llm_layer_dir)
    model = AutoModel.from_pretrained(model_id, **kw)
    tok = model.tokenizer

    def generate(messages: list[dict], max_new_tokens: int) -> str:
        templated = bool(getattr(tok, "chat_template", None))
        if templated:
            # enable_thinking=False switches off Qwen3 thinking; other templates ignore unknown variables
            prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                             enable_thinking=False)
        else:
            prompt = "".join(f"{m['role']}: {m['content']}\n\n" for m in messages) + "assistant: "
        ids = tok(prompt, return_tensors="pt", add_special_tokens=not templated)["input_ids"]
        n_in = ids.shape[1]
        if n_in + max_new_tokens > MAX_SEQ_LEN:
            raise ValueError(f"prompt is {n_in} tokens; the deep tier allows {MAX_SEQ_LEN - max_new_tokens}")
        out = model.generate(ids.to(getattr(model, "device", None) or "cuda"), max_new_tokens=max_new_tokens,
                             use_cache=True, return_dict_in_generate=True)
        return tok.decode(out.sequences[0][n_in:], skip_special_tokens=True)

    return generate


def first_json(text: str | None) -> dict | None:
    """First JSON object in model text; tolerates ```json fences, <think> blocks and trailing words."""
    text = (text or "").rsplit("</think>", 1)[-1]
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text, i)
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


class DeepLLM:
    def __init__(self, settings: Settings, loader: Loader | None = None):
        self.s = settings
        self.provider = (settings.deep_llm_provider or "none").lower()
        self.model = settings.deep_llm_model or None   # None: hardware.recommend() picks on first use
        self._loader = loader or load_airllm
        self._injected = loader is not None
        self._generate: Generate | None = None
        self._lock = asyncio.Lock()                    # one model, one generation at a time
        self._running: asyncio.Future | None = None
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self.provider == "airllm"

    async def aclose(self) -> None:
        self._generate = None                          # drop the model; a timed-out worker keeps its own ref

    async def status(self) -> dict:
        if not self.enabled:
            return {"provider": self.provider, "available": False,
                    "reason": "deep tier disabled (DEEP_LLM_PROVIDER=none)"}
        need = ["torch", "airllm"] + (["bitsandbytes"] if _compression(self.s) else [])
        have = hardware.packages()
        missing = [] if self._injected else [p for p in need if not have.get(p)]
        out = {"provider": "airllm", "model": self.model or "auto (hardware.recommend)",
               "available": not missing, "loaded": self._generate is not None,
               "busy": self._lock.locked() or bool(self._running and not self._running.done()),
               "max_new_tokens": self.s.deep_llm_max_new_tokens, "last_error": self.last_error,
               "note": "slow background tier (seconds per token); advisory, never decides a verdict"}
        if missing:
            out["reason"] = f"missing packages: {', '.join(missing)} (see requirements-airllm.txt)"
        return out

    async def chat_json(self, messages: list[dict], schema: dict, max_tokens: int | None = None) -> dict | None:
        if not self.enabled:
            return None
        cap = self.s.deep_llm_max_new_tokens
        n = min(max_tokens or cap, cap)
        try:
            # no grammar-constrained decoding in AirLLM: put the schema in the prompt instead
            msgs = [*messages[:-1], {**messages[-1], "content": f"{messages[-1]['content']}\n\nReply with one JSON "
                                     f"object only, matching this JSON schema:\n{json.dumps(schema)}"}]
            async with self._lock:
                if self._running is not None and not self._running.done():
                    raise RuntimeError("an earlier deep job that timed out is still running on the GPU")
                self._running = asyncio.ensure_future(asyncio.to_thread(self._work, msgs, n))
                self._running.add_done_callback(lambda f: f.cancelled() or f.exception())  # mark as retrieved
                # shield: on timeout the thread cannot be stopped, so _running keeps tracking it
                text = await asyncio.wait_for(asyncio.shield(self._running), self.s.deep_llm_timeout_s)
        except TimeoutError:
            return self._fail(f"timed out after {self.s.deep_llm_timeout_s:g} s (the worker finishes in the background)")
        except Exception as exc:  # noqa: BLE001 - CUDA OOM, missing packages, download errors: never raise
            return self._fail(f"{type(exc).__name__}: {exc}")
        obj = first_json(text)
        if obj is None:
            return self._fail(f"no JSON object in the output (cap {n} tokens): {text[:200]!r}")
        self.last_error = None
        return obj

    def _work(self, messages: list[dict], n: int) -> str:
        """Worker thread: load once (stored even if the caller already timed out), then generate."""
        if self._generate is None:
            if not self.model:
                rec = hardware.recommend(hardware.probe(self.s.deep_llm_layer_dir))
                if rec["deep"] is None:
                    raise RuntimeError("no deep model for this machine: " + " ".join(rec["notes"]))
                self.model = rec["deep"]["model"]
            log.info("loading AirLLM model %s (a first run downloads and splits it: many GB)", self.model)
            self._generate = self._loader(self.model, self.s)
        return self._generate(messages, n)

    def _fail(self, why: str) -> None:
        self.last_error = why
        log.warning("deep LLM (AirLLM) gave no answer: %s", why)
        return None
