"""Conversation memory (follow-ups) and real-data wording."""
import re

import numpy as np
import pandas as pd

from backend.ai.memory import ConversationMemory, merge_followup
from backend.core.wording import TEST_NOTE, data_note

BAD_WORDS = re.compile(r"\b(invalid|fake|not fit|bogus|wrong data|error in the data)\b", re.I)


def _plan(client, q, cid=None):
    body = {"question": q, **({"conversation_id": cid} if cid else {})}
    return client.post("/api/ai/plan", json=body).json()


# ------------------------------------------------------------------ merge (pure)
def test_merge_explicit_wins_missing_inherited():
    mem = {"variable": {"id": "t"}, "region": {"name": "India"}, "period": {"start": "2002-01", "end": "2022-12"}}
    new = {"variable": {"id": "p"}, "region": {"name": "Kerala"}, "period": {"start": "2001-01", "end": "2024-12"}}
    m, inh = merge_followup(new, mem, {"variable": False, "region": True, "period": False})
    assert m["region"]["name"] == "Kerala" and m["variable"]["id"] == "t" and m["period"]["start"] == "2002-01"
    assert inh == ["variable", "period"]
    m, inh = merge_followup(new, mem, {"variable": True, "region": True, "period": True})
    assert m == new and inh == []
    m, inh = merge_followup(new, None, {"variable": False, "region": False, "period": False})
    assert m == new and inh == []


def test_memory_caps_turns_and_conversations():
    mem = ConversationMemory(max_conversations=2, max_turns=3)
    for i in range(5):
        mem.add_turn("a", "user", f"q{i}")
    assert [t["text"] for t in mem.turns("a", 10)] == ["q2", "q3", "q4"]
    mem.remember_plan("b", {"region": {"name": "x"}})
    mem.remember_plan("c", {"region": {"name": "y"}})
    assert mem.get_plan("a") is None and mem.get_plan("c")["region"]["name"] == "y"


# ------------------------------------------------------------------ API follow-ups
def test_followup_inherits_variable_and_period(client):
    client.fake.llm_reply = None
    first = _plan(client, "Is temperature rising in India from 2002 to 2022?")
    cid = first["conversation_id"]
    vid = first["variables"][0]["id"]
    assert first["context"]["inherited"] == []
    p = _plan(client, "what about Kerala?", cid)
    assert p["on_topic"], p
    assert p["regions"][0]["name"].lower().startswith("kerala")
    assert p["variables"][0]["id"] == vid
    assert p["period"]["start"] == first["period"]["start"] and p["period"]["end"] == "2022-12"
    assert set(p["context"]["inherited"]) == {"variable", "period"}
    assert p["message"].startswith("Using:") and "Kept from earlier" in p["message"]


def test_followup_explicit_period_and_variable_override(client):
    client.fake.llm_reply = None
    cid = _plan(client, "Is temperature rising in India from 2002 to 2022?")["conversation_id"]
    p = _plan(client, "and since 1990?", cid)
    assert p["regions"][0]["name"] == "India" and "period" not in p["context"]["inherited"]
    assert p["context"]["inherited"] == ["variable", "region"]
    p = _plan(client, "show rainfall instead", cid)
    assert "variable" not in p["context"]["inherited"]
    assert "precip" in p["variables"][0]["id"] or "rain" in p["variables"][0]["name"].lower()
    assert p["regions"][0]["name"] == "India"


def test_conversations_are_isolated(client):
    client.fake.llm_reply = None
    a = _plan(client, "Is temperature rising in India from 2002 to 2022?")["conversation_id"]
    b = _plan(client, "Is rainfall changing in Chennai since 2001?")["conversation_id"]
    assert a != b
    pa = _plan(client, "why?", a)
    pb = _plan(client, "why?", b)
    assert pa["regions"][0]["name"] == "India" and pb["regions"][0]["name"] == "Chennai"
    assert "drivers" in pa["wishes"] and pa["wishes"]["drivers"]
    fresh = _plan(client, "what about Kerala?")
    assert "inherited" not in (fresh.get("context") or {}) or fresh["context"]["inherited"] == []


def test_ask_followup_gets_history_and_is_verified(client):
    seen = []

    def reply(body):
        seen.append(body["messages"])
        return "Temperature in India is caused by many things."
    client.fake.llm_reply = None
    cid = client.post("/api/ai/ask", json={"question": "Is temperature rising in India?"}).json()["conversation_id"]
    _plan(client, "Is temperature rising in India from 2002 to 2022?", cid)
    client.fake.llm_reply = reply
    r = client.post("/api/ai/ask", json={"question": "why?", "conversation_id": cid}).json()
    assert r["on_topic"] and r["conversation_id"] == cid
    assert any(m["content"].startswith("Is temperature rising in India") for m in seen[-1][1:-1])
    assert r["source"] == "deterministic" and not r["verification"]["passed"]   # causal wording rejected
    assert r["context"]["region"] == "India"


# ------------------------------------------------------------------ wording
def test_data_note_says_real_and_counts_blanks():
    n = data_note("giovanni", 240, 228, "GPM_3IMERGM")
    assert "real measurements" in n and "NASA" in n and "12 of 240 months" in n and "never filled in" in n
    assert "uploaded file" in data_note("user_upload", 12, 12)
    assert "not about whether the data are real" in TEST_NOTE


def test_integrity_and_active_wording_separate_data_from_test():
    from backend.active.engine import LIMIT, check_integrity, detect, label
    from backend.analysis.deseason import deseasonalize
    from backend.novelty.integrity import integrity_audit
    from backend.timeseries.model import MonthlySeries, Provenance
    t = pd.date_range("2001-01-01", periods=60, freq="MS")
    v = np.where(np.arange(60) % 3 == 0, np.nan, np.random.default_rng(1).normal(size=60))
    v[:30] = np.nan
    ms = MonthlySeries(t, v, "K", Provenance("giovanni", "x", {}))
    a = integrity_audit(ms, deseasonalize(ms, "climatology").deseasonalized)
    assert a["badge"] == "NOT_FIT"
    text = " ".join(a["reasons"]) + a["badge_plain"] + a["data_note"]
    assert not BAD_WORDS.search(text), text
    assert "real" in a["data_note"] and "never filled in" in text and "NASA" in a["data_note"]
    assert "not about whether the data are real" in a["test_note"]
    d = detect(ms)
    assert d["state"] == "too_short" and "data are real" in d["plain_language"]
    assert not BAD_WORDS.search(LIMIT) and "still real" in LIMIT
    rng = np.random.default_rng(2)
    t2 = pd.date_range("1995-01-01", periods=360, freq="MS")
    ms2 = MonthlySeries(t2, rng.normal(size=360), "K", Provenance("ncei.ads", "x", {}))
    det = detect(ms2)
    c = check_integrity(ms2, det)
    assert not BAD_WORDS.search(c["plain_language"])
    lab = label(det, [c, {"check": "court", "status": "fail", "plain_language": ""}], None)
    assert lab["label"] == "NOT VERIFIED" and "NOAA" in lab["data_note"] and lab["test_note"] == TEST_NOTE
    assert not BAD_WORDS.search(lab["plain_language"])


def test_explanation_has_data_real_sentence(client):
    from tests.test_api import make_series
    client.fake.llm_reply = None
    sid = make_series(client)
    r = client.post("/api/ai/explain", json={"series_id": sid, "include_insights": False}).json()
    assert r["source"] == "deterministic"
    assert ("real measurements" in r["explanation"] or "uploaded file" in r["explanation"])
    assert "not about whether the data are real" in r["explanation"]
    assert "SIGNIFICANT" in r["explanation"] or "NOT PROVEN" in r["explanation"]
    assert r["data_note"] and not BAD_WORDS.search(r["explanation"])
