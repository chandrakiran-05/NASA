"""Planner-only run over the 100-question bank (no data fetching, no LLM).

Checks that the deterministic planner finds a place and picks a variable of the expected
criterion (criteria.json) for nearly every question.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.active.runner import CRITERIA
from backend.ai.assistant import AIService
from backend.ai.llm import LocalLLM
from backend.catalog.catalog import load_catalog
from backend.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = json.loads((ROOT / "scripts" / "question_bank.json").read_text(encoding="utf-8"))["questions"]
CRIT = {c["id"]: c for c in CRITERIA}
# regressions seen in the live run: a feature name must win over a city/state hidden inside it
FIRST_PLACE = {
    "Is the North Atlantic sea surface warming since 1980?": "North Atlantic Ocean",
    "Is the water level of Lake Superior changing since 1990?": "Lake Superior",
    "Is Lake Victoria water level rising?": "Lake Victoria",
    "Is the Great Salt Lake level falling since 1990?": "Great Salt Lake",
    "Is the Colorado River flow decreasing since 1990?": "Colorado River",
    "Is the Mekong River water level falling?": "Mekong River",
    "Is river runoff in the Ganges basin changing since 2001?": "Ganges Basin",
    "Is oil pollution increasing in the Gulf of Guinea?": "Gulf of Guinea",
}


def _plans(tmp_path) -> list[tuple[dict, dict]]:
    s = Settings(data_dir=tmp_path / "data", llm_provider="none", _env_file=None)
    ai = AIService(s, load_catalog(None), LocalLLM(s))
    return [(item, asyncio.run(ai.plan(item["q"]))) for item in QUESTIONS]


def test_planner_bank(tmp_path):
    place_fail, var_fail, n_place, n_var = [], [], 0, 0
    for item, plan in _plans(tmp_path):
        q, want = item["q"], item["criterion"]
        if want == "off_topic":
            assert not plan["on_topic"], q
            continue
        if not plan["on_topic"]:
            var_fail.append(f"{q} -> refused as off-topic")
            plan = {"regions": [], "variables": []}
        n_place += 1
        # an archetype example region (e.g. "Pantanal" for Lake Mead) is not the place the student named
        named = [r for r in plan["regions"] if r.get("kind") != "example"]
        if not named:
            place_fail.append(q)
        elif q in FIRST_PLACE:
            assert named[0]["name"] == FIRST_PLACE[q], (q, named[0]["name"])
        assert all(r["approximate"] for r in named if r["kind"] in ("region", "country", "us_state")), q
        if CRIT[want]["status"] == "not_trendable":
            continue
        n_var += 1
        top = plan["variables"][0]["id"] if plan["variables"] else None
        if top not in CRIT[want]["variables"]:
            var_fail.append(f"{q} -> {top} (want {want})")
    print(f"\nplace found {n_place - len(place_fail)}/{n_place}; variable in criterion {n_var - len(var_fail)}/{n_var}")
    for f in place_fail:
        print("NO PLACE:", f)
    for f in var_fail:
        print("VARIABLE:", f)
    assert n_place - len(place_fail) >= 95
    assert n_var - len(var_fail) >= 90



def test_everyday_words_reach_the_scientific_criterion():
    from backend.catalog.catalog import expand_everyday
    assert "temperature" in expand_everyday("is chennai getting hotter?")
    assert "precipitation" in expand_everyday("india rains")
    assert expand_everyday("NDVI in Kenya") == "NDVI in Kenya"
