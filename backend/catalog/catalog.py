"""Variable catalog: seed entries (verified IDs from the reference doc) merged with the
catalog built from official listing endpoints (scripts/build_catalog.py -> data/catalog_built.json).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..ai.bm25 import BM25
from ..core.errors import NotFound

DATA = Path(__file__).parent / "data"


@dataclass
class Catalog:
    variables: dict[str, dict]
    archetypes: list[dict]
    topics: dict[str, list[str]]
    alerts: dict
    built_at: str | None = None

    def __post_init__(self):
        self._ids = list(self.variables)
        self._index = BM25([self._doc(self.variables[i]) for i in self._ids])
        self._arch_index = BM25([" ".join([a["name"], *a["keywords"]]) for a in self.archetypes])

    @staticmethod
    def _doc(v: dict) -> str:
        parts = [v.get("name", ""), v.get("short_definition", ""), v.get("definition", ""),
                 " ".join(v.get("keywords", [])), v.get("family", "").replace("_", " "), v.get("domain", ""),
                 (v.get("dataset") or {}).get("short_name") or "", (v.get("dataset") or {}).get("variable") or ""]
        # the name counts three times and keywords twice: they are the curated vocabulary
        return " ".join(parts) + " " + " ".join(v.get("keywords", [])) + (" " + v.get("name", "")) * 2

    # ------------------------------------------------------------------
    def get(self, vid: str) -> dict:
        v = self.variables.get(vid)
        if v is None:
            # also accept a Giovanni ID or AppEEARS product/layer
            for cand in self.variables.values():
                if vid in (cand.get("giovanni_id"), f"{cand.get('product_id')}/{cand.get('layer')}"):
                    return cand
            raise NotFound(f"Unknown variable {vid!r}")
        return v

    def search(self, q: str | None = None, domain: str | None = None, region_type: str | None = None,
               source: str | None = None, limit: int = 20) -> list[dict]:
        ids = self._ids
        scores = dict.fromkeys(ids, 0.0)
        if q:
            for i, s in zip(ids, self._index.scores(q)):
                # small prior for the canonical variable of each family (only if it already matches)
                scores[i] = s + (0.5 if s > 0 and self.variables[i].get("canonical") else 0.0)
            for topic, vids in self.topics.items():
                if topic in q.lower():
                    for vid in vids:
                        if vid in scores:
                            scores[vid] += 2.0
        if region_type:
            arch = self.archetype(region_type)
            if arch:
                # a query that names a quantity ("temperature") must not be overridden by the region type
                best_q = max(scores.values()) if q else 0.0
                weight = 0.25 if best_q > 1.2 else 1.0
                for rank, rv in enumerate(arch["variables"]):
                    if rv["id"] in scores:
                        scores[rv["id"]] += weight * (5.0 - 0.5 * rank)
        out = []
        for vid in ids:
            v = self.variables[vid]
            if domain and v.get("domain") != domain:
                continue
            if source and v.get("source") != source:
                continue
            if (q or region_type) and scores[vid] <= 0:
                continue
            out.append((scores[vid], vid))
        out.sort(key=lambda x: (-x[0], x[1]))
        return [self.summary(self.variables[vid], score=s) for s, vid in out[:limit]]

    def summary(self, v: dict, score: float | None = None) -> dict:
        conv = v.get("convert") or {}
        d = {
            "id": v["id"], "name": v["name"], "definition": v.get("short_definition"),
            "units": conv.get("units") or v.get("units"), "source": v["source"], "domain": v.get("domain"),
            "family": v.get("family"), "temporal_res": v.get("native_resolution"),
            "coverage_start": v.get("coverage_start"), "coverage_end": v.get("coverage_end"),
            "spatial_mode": v.get("spatial_modes", ["point", "area"]), "land_only": v.get("land_only", False),
            "verified": v.get("verified", False),
        }
        if score is not None:
            d["score"] = round(float(score), 3)
        return d

    def detail(self, vid: str) -> dict:
        v = self.get(vid)
        d = self.summary(v)
        ds = v.get("dataset") or {}
        d.update({
            "long_definition": v.get("definition"), "keywords": v.get("keywords", []),
            "dataset": ds, "native_units": v.get("units"), "unit_conversion": v.get("convert"),
            "giovanni_id": v.get("giovanni_id"), "appeears": ({"product": v.get("product_id"), "layer": v.get("layer")}
                                                              if v.get("product_id") else None),
            "fallback": v.get("fallback"), "definition_source": v.get("definition_source", "editorial"),
            "units_source": v.get("units_source"), "coverage_source": v.get("coverage_source"),
        })
        if ds.get("concept_id"):
            d["cmr_link"] = f"https://cmr.earthdata.nasa.gov/search/concepts/{ds['concept_id']}.html"
        if ds.get("doi"):
            d["doi_link"] = f"https://doi.org/{ds['doi']}"
        d["alerts"] = self.alerts_for(v)
        return d

    def archetype(self, key: str) -> dict | None:
        k = (key or "").lower().strip()
        for a in self.archetypes:
            if a["id"] == k or a["name"].lower() == k:
                return a
        hits = self._arch_index.top(k, 1, 0.5)
        return self.archetypes[hits[0][0]] if hits else None

    def match_archetypes(self, text: str, k: int = 2) -> list[dict]:
        return [self.archetypes[i] for i, s in self._arch_index.top(text, k, 0.8)]

    def alerts_for(self, v: dict) -> list[dict]:
        gid = v.get("giovanni_id") or ""
        out = []
        for a in self.alerts.get("alerts", []):
            prefixes = a.get("outage_giovanni_prefixes", []) + a.get("affected_giovanni_prefixes", [])
            if gid and any(gid.startswith(p) for p in prefixes):
                out.append({"id": a["id"], "severity": a["severity"], "message": a["message"]})
            elif a["id"] == "land-ocean-mask" and v.get("land_only"):
                out.append({"id": a["id"], "severity": a["severity"], "message": a["message"]})
        return out

    def in_outage(self, v: dict, point: bool = False) -> bool:
        gid = (v.get("giovanni_point_id") if point else None) or v.get("giovanni_id") or ""
        return any(gid.startswith(p) for a in self.alerts.get("alerts", [])
                   for p in a.get("outage_giovanni_prefixes", []))

    @property
    def index(self) -> BM25:
        return self._index

    @property
    def ids(self) -> list[str]:
        return self._ids


def load_catalog(data_dir: Path | None = None) -> Catalog:
    seed = json.loads((DATA / "seed_catalog.json").read_text())
    arch = json.loads((DATA / "archetypes.json").read_text())
    alerts = json.loads((DATA / "alerts.json").read_text())
    variables = {v["id"]: v for v in seed["variables"]}
    built_at = None
    if data_dir is not None:
        built = data_dir / "catalog_built.json"
        if built.exists():
            b = json.loads(built.read_text())
            built_at = b.get("built_at")
            for vid, patch in b.get("updates", {}).items():   # official metadata overrides seed values
                if vid in variables:
                    variables[vid].update(patch)
            for v in b.get("additional", []):                 # extra official variables (no editorial text)
                variables.setdefault(v["id"], v)
    return Catalog(variables, arch["archetypes"], arch.get("topics", {}), alerts, built_at)
