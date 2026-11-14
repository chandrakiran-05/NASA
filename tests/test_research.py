"""Research Evidence: literature parsing, abstract reading, AI-slop guard, agreement, best-trend choice."""
import asyncio
import json

import httpx

from backend.core.config import Settings
from backend.core.http import ResilientHTTP
from backend.research import evidence as ev
from backend.research.evidence import (agreement, choose_best, read_stance, research_evidence,
                                       verify_ai_reading)

TERMS = ["NDVI", "vegetation greenness", "greening"]
ABS_UP = ("We analysed MODIS data for 2001-2022. NDVI increased significantly across the Sahel, "
          "indicating widespread greening. Rainfall explained part of the variability.")
ABS_DOWN = "Using satellite records we find that NDVI declined in the Sahel after 2010 because of grazing pressure."
ABS_FLAT = "NDVI showed no significant trend in the Sahel over the study period."


def test_read_stance_only_counts_sentences_naming_the_variable():
    assert read_stance(ABS_UP, TERMS)["stance"] == "rising"
    assert read_stance(ABS_DOWN, TERMS)["stance"] == "falling"
    assert read_stance(ABS_FLAT, TERMS)["stance"] == "no_trend"
    assert read_stance("Rainfall increased strongly.", TERMS)["stance"] == "unclear"   # wrong variable


def test_ai_reading_rejected_unless_quote_is_verbatim_and_supports_the_claim():
    good = {"stance": "rising", "evidence_quote": "NDVI increased significantly across the Sahel, indicating widespread greening."}
    assert verify_ai_reading(ABS_UP, good)[0]
    invented = {"stance": "rising", "evidence_quote": "NDVI rose by 40 percent in every Sahel country."}
    assert verify_ai_reading(ABS_UP, invented) == (False, "quote is not in the abstract")
    wrong = {"stance": "falling", "evidence_quote": "NDVI increased significantly across the Sahel, indicating widespread greening."}
    assert not verify_ai_reading(ABS_UP, wrong)[0]


def test_agreement_labels():
    P = lambda st, rel=3.0: {"stance": st, "relevance": rel, "region_match": True}  # noqa: E731
    assert agreement("rising", [P("rising"), P("rising"), P("falling", 1)])["label"] == "supported"
    assert agreement("rising", [P("falling"), P("falling")])["label"] == "conflicts"
    assert agreement("rising", [P("rising"), P("falling")])["label"] == "mixed"
    assert agreement("rising", [])["label"] == "no_literature"


def test_best_trend_never_picks_not_verified_and_uses_research():
    def tr(vid, lab, eff, lit):
        return {"variable_id": vid, "name": vid, "detect": {"effect_sd_per_decade": eff, "plain_language": vid},
                "verdict": {"label": lab, "why": "x"}, "research": {"agreement": {"label": lit}, "plain_language": lit}}
    b = choose_best([tr("a", "NOT VERIFIED", 3.0, "supported"), tr("b", "VERIFIED", 0.5, "conflicts"),
                     tr("c", "VERIFIED", 0.5, "supported")])
    assert b["best"]["variable_id"] == "c" and all(r["variable_id"] != "a" for r in b["ranking"])
    assert choose_best([tr("a", "NOT VERIFIED", 1, "supported")])["best"] is None


def _transport(log):
    atom = ("<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>http://arxiv.org/abs/1</id>"
            "<published>2024-05-01T00:00:00Z</published><title>Sahel NDVI trends</title>"
            f"<summary>{ABS_UP}</summary><author><name>A Author</name></author></entry></feed>")
    words = ABS_DOWN.split()
    inv = {}
    for i, w in enumerate(words):
        inv.setdefault(w, []).append(i)

    def handler(req: httpx.Request):
        log.append(req.url.host)
        if req.url.host == "export.arxiv.org":
            return httpx.Response(200, text=atom)
        if req.url.host == "api.openalex.org":
            return httpx.Response(200, json={"results": [
                {"id": "W1", "doi": "https://doi.org/10.1/x", "title": "Browning of the Sahel NDVI",
                 "publication_year": 2023, "abstract_inverted_index": inv, "type": "article",
                 "primary_location": {"source": {"display_name": "RSE", "type": "journal"}},
                 "authorships": [{"author": {"display_name": "B Writer"}}]},
                {"id": "W2", "doi": "https://doi.org/10.1/y", "title": "Sahel NDVI greening continues",
                 "publication_year": 2025, "abstract_inverted_index": {w: [i] for i, w in enumerate(ABS_UP.split())},
                 "type": "article", "primary_location": {"source": {"display_name": "GRL", "type": "journal"}},
                 "authorships": [{"author": {"display_name": "C Author"}}]}]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    async def chat_json(self, *a, **k):
        return self.reply


def test_research_evidence_end_to_end_with_ai_slop_guard(tmp_path):
    hosts = []
    http = ResilientHTTP(Settings(data_dir=tmp_path, http_max_retries=0), transport=_transport(hosts))
    slop = FakeLLM({"stance": "rising", "region_matches": True, "evidence_quote": "NDVI doubled everywhere in Africa."})
    r = asyncio.run(research_evidence(http, slop, variable_id="modis_ndvi_monthly", variable_name="NDVI",
                                      region_name="Sahel", direction="rising"))
    assert {"export.arxiv.org", "api.openalex.org"} <= set(hosts)
    assert r["n_relevant"] == 3 and r["agreement"]["label"] == "supported"
    assert r["ai_readings"]["accepted"] == 0 and r["ai_readings"]["rejected_as_unsupported"] == 3
    assert all(p["read_by"] == "lexicon" for p in r["papers"])
    assert "doi:10.1/y" in r["plain_language"]
    assert any(s["source"] == "Springer Nature" and s["status"] == "not_configured" for s in r["sources"])
    asyncio.run(http.aclose())


def test_research_unavailable_sources_are_reported_not_fatal(tmp_path):
    http = ResilientHTTP(Settings(data_dir=tmp_path, http_max_retries=0),
                         transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    r = asyncio.run(research_evidence(http, None, variable_id="merra2_t2m", variable_name="Air temperature",
                                      region_name="Chennai", direction="rising"))
    assert r["agreement"]["label"] == "no_literature" and r["n_relevant"] == 0
    assert all(s["status"] != "ok" for s in r["sources"])
    asyncio.run(http.aclose())


def test_terms_cover_catalog_families():
    assert ev.terms_for("imerg_precip_monthly", None)[0] == "precipitation"
    assert ev.terms_for("modis_lst_day", None)[0] == "land surface temperature"
    assert ev.terms_for("unknown_var", "Mystery")[0] == "Mystery"
