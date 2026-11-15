"""Conversation memory for follow-up questions ("what about Kerala?", "and since 1990?", "why?").

In-memory, per process, capped by count and age. Each conversation keeps:
* the last resolved plan: variable, region, period (+ last report / series ids)
* the last few turns (role, text), given to the local LLM as context for /ai/ask

The merge is deterministic: whatever the new question names explicitly (variable, place, years) wins;
whatever it leaves out is inherited from the remembered plan, and the response says what was inherited.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections import OrderedDict

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_id() -> str:
    return "c_" + uuid.uuid4().hex[:16]


def valid_id(cid: str | None) -> bool:
    return bool(cid and ID_RE.match(cid))


class ConversationMemory:
    def __init__(self, max_conversations: int = 500, max_age_s: float = 6 * 3600, max_turns: int = 8):
        self.max_conversations = max_conversations
        self.max_age_s = max_age_s
        self.max_turns = max_turns
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        for cid in [c for c, d in self._data.items() if now - d["updated"] > self.max_age_s]:
            del self._data[cid]
        while len(self._data) > self.max_conversations:
            self._data.popitem(last=False)

    def _entry(self, cid: str) -> dict:
        now = time.monotonic()
        self._prune(now)
        d = self._data.get(cid)
        if d is None:
            d = self._data[cid] = {"plan": None, "turns": [], "updated": now}
        d["updated"] = now
        self._data.move_to_end(cid)
        return d

    def get_plan(self, cid: str | None) -> dict | None:
        if not cid:
            return None
        with self._lock:
            self._prune(time.monotonic())
            d = self._data.get(cid)
            return dict(d["plan"]) if d and d["plan"] else None

    def remember_plan(self, cid: str, plan: dict) -> None:
        with self._lock:
            d = self._entry(cid)
            merged = dict(d["plan"] or {})
            merged.update({k: v for k, v in plan.items() if v is not None})
            d["plan"] = merged

    def add_turn(self, cid: str, role: str, text: str) -> None:
        with self._lock:
            d = self._entry(cid)
            d["turns"].append({"role": role, "text": (text or "")[:600]})
            d["turns"] = d["turns"][-self.max_turns:]

    def turns(self, cid: str | None, n: int = 4) -> list[dict]:
        if not cid:
            return []
        with self._lock:
            d = self._data.get(cid)
            return [dict(t) for t in (d["turns"][-n:] if d else [])]

    def forget(self, cid: str) -> None:
        with self._lock:
            self._data.pop(cid, None)


def period_text(period: dict | None) -> str | None:
    if not period or not period.get("start"):
        return None
    a, b = str(period["start"])[:4], str(period.get("end") or "")[:4]
    return f"{a}–{b}" if b else f"since {a}"


def summary_of(plan: dict | None) -> str:
    if not plan:
        return ""
    parts = [(plan.get("variable") or {}).get("name"), (plan.get("region") or {}).get("name"),
             period_text(plan.get("period"))]
    return ", ".join(p for p in parts if p)


def merge_followup(new: dict, remembered: dict | None, explicit: dict) -> tuple[dict, list[str]]:
    """Merge a new resolved plan with the remembered one.

    new        : {"variable": {...}|None, "region": {...}|None, "period": {...}|None}
    remembered : same shape (or None)
    explicit   : {"variable": bool, "region": bool, "period": bool} — what the new question named
    Returns (merged, inherited_keys). Explicit parts always win; missing parts are inherited.
    """
    merged, inherited = {}, []
    for key in ("variable", "region", "period"):
        if explicit.get(key) and new.get(key):
            merged[key] = new[key]
        elif remembered and remembered.get(key):
            merged[key] = remembered[key]
            inherited.append(key)
        else:
            merged[key] = new.get(key)
    return merged, inherited
