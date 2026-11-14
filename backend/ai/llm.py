"""Local LLM client (offline). Two providers:

* ollama  -> POST {base}/api/chat with `format` = JSON schema for structured output, think=false
* openai  -> POST {base}/v1/chat/completions (llama.cpp server, LM Studio, vLLM, Ollama /v1)

Nothing is sent to the internet: base URLs point at the local machine by default.
If the server is not running, every caller falls back to deterministic logic.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..core.config import Settings

log = logging.getLogger("etd.llm")


class LocalLLM:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self.provider = (settings.llm_provider or "none").lower()
        self.base = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_s, transport=transport)
        self._available: bool | None = None
        self._checked = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def enabled(self) -> bool:
        return self.provider in ("ollama", "openai")

    async def status(self, force: bool = False) -> dict:
        if not self.enabled:
            return {"provider": self.provider, "available": False, "reason": "LLM disabled (LLM_PROVIDER=none)"}
        if not force and self._available is not None and time.monotonic() - self._checked < 30:
            return {"provider": self.provider, "model": self.model, "available": self._available}
        try:
            if self.provider == "ollama":
                r = await self._client.get(f"{self.base}/api/tags", timeout=3.0)
                models = [m.get("name") for m in r.json().get("models", [])]
                ok = r.status_code == 200 and any(self.model.split(":")[0] in (m or "") for m in models)
                info = {"installed_models": models[:20]}
                if r.status_code == 200 and not ok:
                    info["hint"] = f"run: ollama pull {self.model}"
            else:
                r = await self._client.get(f"{self.base}/v1/models", timeout=3.0)
                ok = r.status_code == 200
                info = {}
        except (httpx.HTTPError, ValueError) as exc:
            ok, info = False, {"reason": f"local LLM server not reachable at {self.base} ({type(exc).__name__})"}
        self._available, self._checked = ok, time.monotonic()
        return {"provider": self.provider, "model": self.model, "available": ok, **info}

    async def chat(self, messages: list[dict], *, schema: dict | None = None, max_tokens: int | None = None,
                   temperature: float | None = None) -> str | None:
        """Returns the assistant text, or None if the local model is unavailable / errors."""
        if not self.enabled:
            return None
        st = await self.status()
        if not st.get("available"):
            return None
        temp = self.s.llm_temperature if temperature is None else temperature
        ntok = max_tokens or self.s.llm_max_tokens
        try:
            if self.provider == "ollama":
                body = {"model": self.model, "messages": messages, "stream": False, "think": False,
                        "options": {"temperature": temp, "num_predict": ntok}, "keep_alive": "30m"}
                if schema is not None:
                    body["format"] = schema
                r = await self._client.post(f"{self.base}/api/chat", json=body)
                r.raise_for_status()
                return r.json().get("message", {}).get("content")
            body = {"model": self.model, "messages": messages, "temperature": temp, "max_tokens": ntok}
            if schema is not None:
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": "out", "schema": schema, "strict": True}}
            r = await self._client.post(f"{self.base}/v1/chat/completions", json=body)
            if r.status_code == 400 and schema is not None:      # server without json_schema support
                body["response_format"] = {"type": "json_object"}
                r = await self._client.post(f"{self.base}/v1/chat/completions", json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("local LLM call failed: %s", exc)
            self._available = False
            return None

    async def chat_json(self, messages: list[dict], schema: dict, **kw) -> dict | None:
        txt = await self.chat(messages, schema=schema, **kw)
        if not txt:
            return None
        txt = txt.strip()
        if txt.startswith("```"):
            txt = txt.strip("`").split("\n", 1)[-1]
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            s, e = txt.find("{"), txt.rfind("}")
            if s >= 0 and e > s:
                try:
                    return json.loads(txt[s:e + 1])
                except json.JSONDecodeError:
                    return None
            return None
