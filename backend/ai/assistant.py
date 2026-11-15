"""Offline AI service: question -> plan, grounded Q&A, and fact-checked explanations.

Design rule: deterministic logic produces every number and every plan; the local LLM only
(a) improves the plan within validated choices and (b) rephrases facts. Its output is
validated (ids must exist, coordinates in range) and number-checked before it reaches users.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

from pathlib import Path

from ..catalog.catalog import Catalog
from ..core.config import Settings
from ..core.geometry import Region
from . import gazetteer
from .bm25 import BM25
from ..core.wording import TEST_NOTE, data_note, data_real_sentence
from .guard import REFUSAL, check_topic
from .llm import LocalLLM
from .memory import ConversationMemory, merge_followup, summary_of
from .prompts import (ASK_INSTRUCTIONS, EXPLAIN_INSTRUCTIONS, PLAN_INSTRUCTIONS, PLAN_SCHEMA, SYSTEM_BASE)

LAST_FULL_YEAR = date.today().year - 1


def parse_years(text: str) -> tuple[int | None, int | None, str | None]:
    t = text.lower()
    m = re.search(r"(?:from|between)\s+(\d{4})\s*(?:to|and|-|–|until|till|through)\s*(\d{4})", t) or \
        re.search(r"\b(19[89]\d|20\d\d)\s*(?:[-–]|to|until|till|through)\s*(19[89]\d|20\d\d)\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return min(a, b), max(a, b), m.group(0)
    m = re.search(r"(?:last|past)\s+(\d{1,2})\s+years", t)
    if m:
        n = int(m.group(1))
        return LAST_FULL_YEAR - n + 1, LAST_FULL_YEAR, m.group(0)
    m = re.search(r"(?:since|after|from)\s+(19[89]\d|20\d\d)", t)
    if m:
        return int(m.group(1)), LAST_FULL_YEAR, m.group(0)
    return None, None, None


def detect_wishes(text: str) -> dict:
    t = text.lower()
    return {
        "forecast": bool(re.search(r"\b(future|forecast|predict|projection|will it|by 20[3-9]\d|next \d+ years)\b", t)),
        "compare": bool(re.search(r"\b(compare|comparison|versus|vs\.?|difference between|than in)\b", t)),
        "drivers": bool(re.search(r"\b(why|cause|caused|because|driver|drivers|related to|linked to|due to)\b", t)),
        "point": bool(re.search(r"\b(station|exact point|at the point|pixel)\b", t)),
        "when": bool(re.search(r"\b(when did|since when|when was|start(?:ed)? to|began|begin|shift(?:ed)?|sudden|"
                               r"abrupt|turning point|change ?point|break)\b", t)),
        "how_long": bool(re.search(r"\b(how long|how many (?:more )?years|when will (?:we|it)|emerge\w*|"
                                   r"enough data|significant yet)\b", t)),
    }


def intents_of(wishes: dict) -> list[str]:
    """Question types answered by Trend Forensics: what / when / why / how_long (+ compare, forecast)."""
    out = ["what"]
    out += [k for k, name in (("when", "when"), ("drivers", "why"), ("how_long", "how_long"),
                              ("compare", "compare"), ("forecast", "forecast")) if wishes.get(k)]
    return [("why" if i == "drivers" else i) for i in out]


GLOSSARY = Path(__file__).resolve().parents[1] / "catalog" / "data" / "glossary.json"


class AIService:
    def __init__(self, settings: Settings, catalog: Catalog, llm: LocalLLM):
        self.s = settings
        self.catalog = catalog
        self.llm = llm
        self.memory = ConversationMemory()
        self.glossary = json.loads(GLOSSARY.read_text(encoding="utf-8"))["terms"]
        self._gidx = BM25([f"{g['term']} {g['term']} {g['id'].replace('_', ' ')} {g['text']}" for g in self.glossary],
                          drop_question_words=False)

    def glossary_hits(self, text: str, k: int = 2) -> list[dict]:
        return [self.glossary[i] for i, sc in self._gidx.top(text, k, 1.5)]

    # ------------------------------------------------------------------ guard
    def guard(self, text: str) -> dict:
        g = check_topic(text, self.catalog.index, self.s.ai_guard_threshold)
        blocked = any(r.startswith("off-topic") for r in g.reasons)
        if not g.on_topic and not blocked:
            gl = max(self._gidx.scores(text) or [0.0])
            bonus = min(gl / 3.0, 1.5)
            if self.catalog.match_criteria(text):     # names one of the investigation criteria
                bonus += 1.0
            if g.score > 0 and gazetteer.find_places(text, 1):
                bonus += 0.5
            if bonus > 0:
                g.score += bonus
                g.reasons.append(f"methods/place bonus {bonus:.2f}")
                g.on_topic = g.score >= self.s.ai_guard_threshold
        return g.to_dict()

    # ------------------------------------------------------------------ plan
    def _deterministic_plan(self, question: str) -> dict:
        wishes = detect_wishes(question)
        y0, y1, ytxt = parse_years(question)
        places = gazetteer.find_places(question, max_n=4)
        archs = self.catalog.match_archetypes(question, k=1)
        arch = archs[0] if archs else None
        # a quantity asked about an ocean region ("Is the Gulf of Mexico warming?") is the ocean's quantity
        q = question + (" ocean" if any(p.get("kind") == "ocean" for p in places) else "")
        variables = self.catalog.search(q=q, region_type=arch["id"] if arch else None, limit=6)
        if y0 is not None:
            # prefer variables whose record covers the requested start year (stable re-order)
            def starts_late(v):
                cs = v.get("coverage_start")
                return bool(cs) and int(cs[:4]) > y0
            variables = sorted(variables, key=starts_late)
        variables = variables[:3]
        regions = []
        for p in places:
            r = gazetteer.place_to_region(p, as_point=wishes["point"])
            if r:
                regions.append({"name": p["name"], "kind": p["type"], "geometry": r.as_dict(),
                                "approximate": bool(p.get("approximate")),
                                "source": ("offline gazetteer (GeoNames)" if p["type"] != "region" else "editorial region preset")
                                + (" — approximate box" if p.get("approximate") else "")
                                + (f" ({p['note']})" if p.get("note") else "")})
        if not regions and arch and arch.get("example_bbox"):
            eb = arch["example_bbox"]
            regions.append({"name": eb["name"], "kind": "example", "source": f"example region for '{arch['name']}'",
                            "geometry": Region("bbox", tuple(eb["bbox"]), name=eb["name"]).as_dict()})
        start = y0
        coverage_note = None
        if start is not None and variables and variables[0].get("coverage_start"):
            cs0 = int(variables[0]["coverage_start"][:4])
            if cs0 > start:
                coverage_note = (f"{variables[0]['name']} starts in {variables[0]['coverage_start']}; "
                                 f"the period was shortened to begin then.")
                start = cs0 + (0 if variables[0]["coverage_start"][5:7] in ("01", "") else 1)
        if start is None and variables:
            cs = self.catalog.get(variables[0]["id"]).get("coverage_start") or "2001-01"
            start = max(int(cs[:4]) + (1 if cs[5:7] not in ("01", "") else 0), 2001)
        return {
            "question": question,
            "variables": variables,
            "regions": regions,
            "region_type": arch["id"] if arch else None,
            "archetype_rationale": arch["variables"] if arch else None,
            "period": {"start": f"{start}-01" if start else None, "end": f"{(y1 or LAST_FULL_YEAR)}-12",
                       "parsed_from": ytxt, "note": coverage_note},
            "wishes": wishes,
            "intents": intents_of(wishes),
            "needs_user_input": [k for k, ok in (("region", bool(regions)), ("variable", bool(variables))) if not ok],
            "planner": "deterministic",
        }

    async def plan(self, question: str, conversation_id: str | None = None) -> dict:
        t0 = time.perf_counter()
        g = self.guard_followup(question, conversation_id)
        if not g["on_topic"]:
            return {"on_topic": False, "message": REFUSAL, "guard": g}
        plan = self._deterministic_plan(question)
        catalog_lines = "\n".join(f"- {vid}: {self.catalog.variables[vid]['name']}" for vid in self.catalog.ids)
        msgs = [
            {"role": "system", "content": SYSTEM_BASE + "\n" + PLAN_INSTRUCTIONS.format(max_year=LAST_FULL_YEAR)},
            {"role": "user", "content": f"CONTEXT (variables):\n{catalog_lines}\n\nQUESTION: {question}"},
        ]
        out = await self.llm.chat_json(msgs, PLAN_SCHEMA, max_tokens=300)
        if out:
            plan = self._merge_llm_plan(plan, out)
        if conversation_id:
            plan = self.apply_memory(plan, question, conversation_id)
        plan["on_topic"] = True
        plan["guard"] = g
        plan["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return plan

    # ------------------------------------------------------------------ conversation memory
    def guard_followup(self, question: str, conversation_id: str | None) -> dict:
        """Topic guard; a short follow-up ("why?", "what about Kerala?") is judged together with the
        remembered topic of the conversation. Explicitly blocked text stays blocked."""
        g = self.guard(question)
        if g["on_topic"] or not conversation_id:
            return g
        if any(r.startswith("off-topic") for r in g.get("reasons", [])):
            return g
        remembered = self.memory.get_plan(conversation_id)
        if not remembered:
            return g
        topic = " ".join(filter(None, [(remembered.get("variable") or {}).get("name"),
                                       (remembered.get("region") or {}).get("name")]))
        g2 = self.guard(f"{question} {topic}")
        if g2["on_topic"]:
            g2["reasons"] = list(g2.get("reasons", [])) + ["follow-up of the earlier question in this conversation"]
            return g2
        return g

    def explicit_parts(self, question: str, plan: dict) -> dict:
        """Which parts the question itself names (these override the remembered plan)."""
        idx_best = max(self.catalog.index.scores(question) or [0.0])
        var = bool(self.catalog.match_criteria(question)) or idx_best >= 2.0
        reg = any(r.get("kind") != "example" for r in plan.get("regions") or [])
        per = (plan.get("period") or {}).get("parsed_from") not in (None, "local AI", "conversation")
        return {"variable": var, "region": reg, "period": per}

    def apply_memory(self, plan: dict, question: str, conversation_id: str, remember: bool = True) -> dict:
        """Deterministic follow-up merge: explicit parts of the new question win, missing parts are
        inherited from the remembered plan of this conversation."""
        remembered = self.memory.get_plan(conversation_id)
        per = plan.get("period") or {}
        new = {"variable": plan["variables"][0] if plan.get("variables") else None,
               "region": plan["regions"][0] if plan.get("regions") else None,
               "period": {"start": per.get("start"), "end": per.get("end")} if per.get("start") else None}
        explicit = self.explicit_parts(question, plan)
        merged, inherited = merge_followup(new, remembered, explicit)
        if "variable" in inherited:
            v = merged["variable"]
            plan["variables"] = [v] + [x for x in plan.get("variables") or [] if x.get("id") != v.get("id")][:2]
        if "region" in inherited:
            plan["regions"] = [merged["region"]]
        if "period" in inherited:
            plan["period"] = {**per, "start": merged["period"]["start"], "end": merged["period"]["end"],
                              "parsed_from": "conversation", "note": None}
        # keep the period inside the (possibly inherited) variable's record
        v0 = plan["variables"][0] if plan.get("variables") else None
        cs = (v0 or {}).get("coverage_start")
        st = (plan.get("period") or {}).get("start")
        if cs and st and cs[:7] > st[:7]:
            plan["period"]["start"] = cs[:7]
            plan["period"]["note"] = f"{v0['name']} starts in {cs[:7]}; the period was shortened to begin then."
        plan["needs_user_input"] = [k for k, ok in (("region", bool(plan.get("regions"))),
                                                    ("variable", bool(plan.get("variables")))) if not ok]
        pp = plan.get("period") or {}
        resolved = {"variable": v0, "region": plan["regions"][0] if plan.get("regions") else None,
                    "period": {"start": pp["start"], "end": pp.get("end")} if pp.get("start") else None}
        using = summary_of(resolved)
        names = {"variable": "variable", "region": "place", "period": "years"}
        msg = f"Using: {using}." if using else ""
        if inherited:
            msg += " Kept from earlier in this conversation: " + ", ".join(names[k] for k in inherited) + "."
        plan["conversation_id"] = conversation_id
        plan["context"] = {"variable": (v0 or {}).get("name"), "variable_id": (v0 or {}).get("id"),
                           "region": (resolved["region"] or {}).get("name"), "period": resolved["period"],
                           "inherited": inherited, "explicit": [k for k, ok in explicit.items() if ok],
                           "summary": using}
        if msg:
            plan["message"] = msg.strip()
        if remember:
            self.memory.remember_plan(conversation_id, resolved)
            self.memory.add_turn(conversation_id, "user", question)
        return plan

    def remember_report(self, conversation_id: str, question: str, result: dict) -> None:
        """Store what a finished report actually used (variable, region, period, ids)."""
        p = (result or {}).get("plan") or {}
        vid = p.get("variable_id")
        var = None
        if vid:
            var = (self.catalog.summary(self.catalog.variables[vid]) if vid in self.catalog.variables
                   else {"id": vid, "name": p.get("variable_name") or vid, "units": p.get("units")})
        region = ({"name": p.get("region_name"), "kind": "report", "geometry": p.get("geometry"),
                   "source": "earlier report in this conversation"} if p.get("geometry") else None)
        period = {"start": p.get("start"), "end": p.get("end")} if p.get("start") else None
        prov = (result or {}).get("provenance") or {}
        self.memory.remember_plan(conversation_id, {"variable": var, "region": region, "period": period,
                                                    "series_id": prov.get("series_id"),
                                                    "report_id": (result or {}).get("report_id")})
        self.memory.add_turn(conversation_id, "user", question)
        h = (result or {}).get("headline")
        if isinstance(h, dict):
            h = h.get("text") or h.get("plain_language") or h.get("title")
        if isinstance(h, str) and h:
            self.memory.add_turn(conversation_id, "assistant", h)

    def _merge_llm_plan(self, plan: dict, out: dict) -> dict:
        notes = []
        ids = [i for i in (out.get("variable_ids") or []) if i in self.catalog.variables]
        if ids:
            existing = [v["id"] for v in plan["variables"]]
            merged = ids + [i for i in existing if i not in ids]
            plan["variables"] = [self.catalog.summary(self.catalog.variables[i]) for i in merged[:3]]
            notes.append("variables re-ranked by local AI (validated against catalog)")
        y0, y1 = out.get("start_year"), out.get("end_year")
        if plan["period"]["parsed_from"] is None and isinstance(y0, int) and 1980 <= y0 <= LAST_FULL_YEAR:
            if isinstance(y1, int) and y0 < y1 <= LAST_FULL_YEAR:
                plan["period"].update({"start": f"{y0}-01", "end": f"{y1}-12", "parsed_from": "local AI"})
        if not plan["regions"] and out.get("place_name"):
            rec = gazetteer.lookup(out["place_name"])
            if rec:
                r = gazetteer.place_to_region(rec, as_point=plan["wishes"]["point"])
                plan["regions"].append({"name": rec["name"], "kind": rec["type"], "geometry": r.as_dict(),
                                        "source": "offline gazetteer via local AI"})
            elif out.get("approx_lat") is not None and out.get("approx_lon") is not None:
                lat, lon = float(out["approx_lat"]), float(out["approx_lon"])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    from ..core.geometry import point_buffer
                    r = point_buffer(lon, lat, 50, name=out["place_name"])
                    plan["regions"].append({"name": out["place_name"], "kind": "ai_estimate", "geometry": r.as_dict(),
                                            "source": "approximate centre suggested by local AI — please confirm on the map",
                                            "needs_confirmation": True})
        if out.get("wants_forecast"):
            plan["wishes"]["forecast"] = True
        if out.get("wants_compare"):
            plan["wishes"]["compare"] = True
        plan["needs_user_input"] = [k for k, ok in (("region", bool(plan["regions"])),
                                                    ("variable", bool(plan["variables"]))) if not ok]
        plan["intents"] = intents_of(plan["wishes"])
        plan["planner"] = "deterministic + local AI"
        plan["planner_notes"] = notes
        return plan

    # ------------------------------------------------------------------ ask
    async def ask(self, question: str, conversation_id: str | None = None) -> dict:
        from .verify import verify_text
        g = self.guard_followup(question, conversation_id)
        if not g["on_topic"]:
            return {"on_topic": False, "answer": REFUSAL, "guard": g, "source": "guardrail",
                    **({"conversation_id": conversation_id} if conversation_id else {})}
        conv = None
        history = self.memory.turns(conversation_id, 4) if conversation_id else []
        if conversation_id and self.memory.get_plan(conversation_id):
            conv = self.apply_memory(self._deterministic_plan(question), question, conversation_id)["context"]
        elif conversation_id:
            self.memory.add_turn(conversation_id, "user", question)
        archs = self.catalog.match_archetypes(question, k=1)
        search_q = question
        if conv and "variable" in conv["inherited"] and conv.get("variable"):
            search_q = f"{question} {conv['variable']}"
        vars_ = self.catalog.search(q=search_q, region_type=archs[0]["id"] if archs else None, limit=4)
        if conv and conv.get("variable_id") and conv["variable_id"] in self.catalog.variables:
            v0 = self.catalog.summary(self.catalog.variables[conv["variable_id"]])
            vars_ = [v0] + [v for v in vars_ if v["id"] != v0["id"]][:3]
        terms = self.glossary_hits(question)
        ctx = {"methods": [{"term": g["term"], "explanation": g["text"]} for g in terms],
               "variables": [{"id": v["id"], "name": v["name"], "definition": self.catalog.get(v["id"]).get("definition"),
                              "units": v["units"], "coverage_start": v["coverage_start"], "source": v["source"]}
                             for v in vars_],
               "region_suggestion": ({"type": archs[0]["name"], "why": archs[0]["variables"]} if archs else None)}
        if conv:
            ctx["conversation"] = {"variable": conv.get("variable"), "region": conv.get("region"),
                                   "period": conv.get("period"), "kept_from_earlier": conv.get("inherited")}
        fallback = self._fallback_answer(vars_, archs[0] if archs else None, terms)
        if conv and conv.get("summary"):
            fallback = f"Using: {conv['summary']}.\n\n" + fallback
        msgs = [{"role": "system", "content": SYSTEM_BASE + "\n" + ASK_INSTRUCTIONS
                 + ("\nEarlier turns of this conversation come next; use them only to understand what the "
                    "student refers to. They are not new observations." if history else "")}]
        msgs += [{"role": "user" if t["role"] == "user" else "assistant", "content": t["text"]} for t in history]
        msgs.append({"role": "user",
                     "content": f"CONTEXT:\n{json.dumps(ctx, ensure_ascii=False)}\n\nQUESTION: {question}"})
        txt = await self.llm.chat(msgs, max_tokens=320)
        extra = {"context_variables": vars_}
        if conversation_id:
            extra["conversation_id"] = conversation_id
        if conv:
            extra["context"] = conv
            if conv.get("summary"):
                extra["message"] = f"Using: {conv['summary']}."

        def done(out: dict) -> dict:
            if conversation_id and out.get("answer"):
                self.memory.add_turn(conversation_id, "assistant", out["answer"])
            return out

        if txt and "OFF_TOPIC" not in txt:
            v = verify_text(txt, ctx)
            if v["passed"]:
                return done({"on_topic": True, "answer": txt.strip(), "source": "local_llm",
                             "fact_check": v["fact_check"], "verification": v, **extra})
            return done({"on_topic": True, "answer": fallback, "source": "deterministic",
                         "fact_check": v["fact_check"], "verification": v,
                         "note": "Local AI answer rejected by the checker (numbers not in the tool's data, or "
                                 "wording it does not allow).", **extra})
        if txt and "OFF_TOPIC" in txt:
            return {"on_topic": False, "answer": REFUSAL, "source": "local_llm", "guard": g,
                    **({"conversation_id": conversation_id} if conversation_id else {})}
        return done({"on_topic": True, "answer": fallback, "source": "deterministic", **extra})

    @staticmethod
    def _fallback_answer(vars_: list[dict], arch: dict | None, terms: list[dict] | None = None) -> str:
        if terms:
            out = "\n\n".join(f"{g['term']}: {g['text']}" for g in terms)
            if vars_:
                out += "\n\nRelated variables you can test: " + ", ".join(v["name"] for v in vars_[:3]) + "."
            return out
        if not vars_:
            return ("I couldn't match that to a dataset in the catalog. Try naming a quantity such as rainfall, "
                    "temperature, vegetation (NDVI), soil moisture, snow or NO₂ pollution, plus a place.")
        parts = []
        if arch:
            parts.append(f"For a {arch['name'].lower()}, good variables to investigate are:")
        else:
            parts.append("The most relevant variables in the catalog are:")
        for v in vars_[:3]:
            why = ""
            if arch:
                why = next((x["why"] for x in arch["variables"] if x["id"] == v["id"]), "")
            parts.append(f"• {v['name']} — {v['definition']}" + (f" Why: {why}" if why else ""))
        parts.append("Pick a region on the map and a period of 10+ years, then run the trend test.")
        return "\n".join(parts)

    # ------------------------------------------------------------------ explain
    @staticmethod
    def facts_from(analysis: dict, insights: dict | None, catalog_entry: dict | None) -> dict:
        v = analysis.get("verdict", {})
        f = {
            "variable": analysis.get("label"), "units": analysis.get("units"),
            "period": analysis.get("period"), "direction": v.get("direction"),
            "rate_per_decade": v.get("rate_per_decade"), "rate_units": v.get("rate_units"),
            "total_change": v.get("total_change"), "relative_change_pct": v.get("relative_change_pct"),
            "significant": v.get("significant"), "strength": v.get("strength"),
            "p_regression_adjusted": analysis.get("ols", {}).get("p_adj"),
            "p_mann_kendall": analysis.get("mann_kendall", {}).get("p"),
            "ci95_per_decade": analysis.get("ols", {}).get("ci95_adj_per_decade"),
            "tests_agree": v.get("tests_agree"), "caveats": v.get("caveats"),
            "plain_language": v.get("plain_language"),
        }
        per, prov = analysis.get("period") or {}, analysis.get("provenance") or {}
        f["data_note"] = data_note(prov.get("source_api"), per.get("n_months"), per.get("n_valid"),
                                   prov.get("dataset_short_name"))
        f["test_note"] = TEST_NOTE
        if catalog_entry:
            f["variable_definition"] = catalog_entry.get("short_definition")
        if insights:
            for k in ("detectability", "emergence", "breaks", "triangle", "records", "forecast", "onset"):
                if isinstance(insights.get(k), dict) and insights[k].get("plain_language"):
                    f[k] = insights[k]["plain_language"]
            tei = insights.get("trend_evidence_index") or {}
            if tei.get("score") is not None:
                f["trend_evidence_index"] = {"score": tei["score"], "label": tei["label"]}
        return f

    @staticmethod
    def deterministic_explanation(facts: dict) -> str:
        """Three ideas kept apart: (1) the data are real, (2) missing months are left blank, (3) the test
        result is about whether the trend is clear enough, not whether the data are real."""
        parts = [facts.get("data_note") or data_real_sentence(None)]
        parts.append(facts.get("plain_language") or "")
        sig = facts.get("significant")
        if sig is True:
            parts.append("Test result: SIGNIFICANT, the trend is clear enough to stand out from normal ups and downs.")
        elif sig is False:
            parts.append("Test result: NOT PROVEN, the trend is not clear enough yet to stand out from normal ups "
                         "and downs.")
        parts.append(facts.get("test_note") or TEST_NOTE)
        for k in ("breaks", "emergence", "detectability", "triangle"):
            if facts.get(k):
                parts.append(facts[k])
        if facts.get("trend_evidence_index"):
            t = facts["trend_evidence_index"]
            parts.append(f"Trend Evidence Index: {t['score']:.0f}/100 ({t['label']}).")
        if facts.get("caveats"):
            parts.append("Note: " + facts["caveats"][0])
        return " ".join(p for p in parts if p)

    async def explain(self, analysis: dict, insights: dict | None = None, catalog_entry: dict | None = None,
                      drivers: dict | None = None, intents: list[str] | None = None) -> dict:
        from .verify import failure_feedback, verify_text
        facts = self.facts_from(analysis, insights, catalog_entry)
        if drivers and drivers.get("plain_language"):
            facts["drivers"] = drivers["plain_language"]
        if intents:
            facts["question_types"] = intents
        base = self.deterministic_explanation(facts)
        if facts.get("drivers"):
            base += " " + facts["drivers"]
        msgs = [{"role": "system", "content": SYSTEM_BASE + "\n" + EXPLAIN_INSTRUCTIONS},
                {"role": "user", "content": "FACTS:\n" + json.dumps(facts, ensure_ascii=False, default=str)}]
        last = None
        for attempt in range(2):
            txt = await self.llm.chat(msgs, max_tokens=420)
            if not txt:
                break
            v = verify_text(txt, facts)
            last = v
            if v["passed"] and "OFF_TOPIC" not in txt:
                return {"explanation": txt.strip(), "source": "local_llm", "fact_check": v["fact_check"],
                        "verification": v, "facts": facts, "data_note": facts["data_note"],
                        "test_note": facts["test_note"]}
            msgs.append({"role": "assistant", "content": txt})
            msgs.append({"role": "user", "content": "Your text failed verification: " + failure_feedback(v)
                         + ". Rewrite using only FACTS, no causal words, and the correct direction."})
        out = {"explanation": base, "source": "deterministic", "facts": facts, "data_note": facts["data_note"],
               "test_note": facts["test_note"]}
        if last:
            out["verification"] = last
            out["note"] = "Local AI text rejected by the verifier; deterministic text shown."
        return out

    async def suspects(self, target_id: str, region_name: str | None = None, max_n: int = 3) -> list[dict]:
        """Pre-registered WHY hypotheses, made before any data is seen.

        Textbook bundle first; the local AI may add or re-rank, but only with catalog ids from the
        allowed list (anything else is dropped). Neither source sees data; PCMCI+ decides later."""
        bundles = json.loads((GLOSSARY.parent / "driver_bundles.json").read_text(encoding="utf-8"))["bundles"]
        base = [dict(s, source="textbook hypothesis") for s in bundles.get(target_id, [])]
        allowed = sorted({s["driver_id"] for b in bundles.values() for s in b} - {target_id})
        schema = {"type": "object", "properties": {"suspects": {"type": "array", "maxItems": max_n, "items": {
            "type": "object", "properties": {
                "driver_id": {"type": "string", "enum": allowed},
                "expected_sign": {"type": "string", "enum": ["+", "-", "either"]},
                "lag_months": {"type": "integer", "minimum": 0, "maximum": 6},
                "mechanism": {"type": "string"}},
            "required": ["driver_id", "expected_sign", "lag_months", "mechanism"]}}},
            "required": ["suspects"]}
        tname = (self.catalog.variables.get(target_id) or {}).get("name", target_id)
        msgs = [{"role": "system", "content": SYSTEM_BASE + "\nPropose up to 3 physical drivers that could explain "
                 "month-to-month changes of the target variable. Choose driver ids ONLY from the allowed list. You "
                 "have NOT seen any data; these are hypotheses to be tested."},
                {"role": "user", "content": f"TARGET: {target_id} ({tname})\nREGION: {region_name or 'unspecified'}\n"
                 "ALLOWED: " + ", ".join(f"{a} ({(self.catalog.variables.get(a) or {}).get('name', a)})" for a in allowed)}]
        out = await self.llm.chat_json(msgs, schema, max_tokens=300)
        merged, seen = [], set()
        for s in ((out or {}).get("suspects") or []):
            if s.get("driver_id") in allowed and s["driver_id"] not in seen and s.get("expected_sign") in ("+", "-", "either"):
                merged.append({"driver_id": s["driver_id"], "expected_sign": s["expected_sign"],
                               "lag_months": int(s.get("lag_months") or 0), "mechanism": str(s.get("mechanism", ""))[:200],
                               "source": "local AI hypothesis"})
                seen.add(s["driver_id"])
        for s in base:
            if s["driver_id"] not in seen:
                merged.append(s)
                seen.add(s["driver_id"])
        for s in merged:
            s["driver_name"] = (self.catalog.variables.get(s["driver_id"]) or {}).get("name", s["driver_id"])
        return merged[:max_n]
