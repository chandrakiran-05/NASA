"""Earth-topic guardrail: the assistant only answers questions about Earth-system data,
trends and the statistics used to detect them. Deterministic, ~0.1 ms, runs before any LLM call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .bm25 import BM25, stem, tokenize

EARTH_TERMS = {
    # physical earth system
    "climate", "weather", "temperature", "warming", "cooling", "heat", "heatwave", "cold", "rain", "rainfall",
    "precipitation", "drought", "flood", "snow", "snowpack", "ice", "glacier", "permafrost", "ocean", "sea",
    "river", "lake", "wetland", "estuary", "delta", "coast", "soil", "moisture", "vegetation", "forest",
    "deforestation", "greening", "browning", "crop", "agriculture", "irrigation", "desert", "rainforest",
    "savanna", "grassland", "tundra", "arctic", "antarctic", "monsoon", "cyclone", "hurricane", "typhoon", "storm",
    "wind", "cloud", "humidity", "vapor", "vapour", "evaporation", "evapotranspiration", "runoff", "streamflow",
    "groundwater", "atmosphere", "troposphere", "stratosphere", "ozone", "aerosol", "dust", "smoke", "wildfire",
    "fire", "pollution", "smog", "no2", "nitrogen", "co2", "carbon", "methane", "emissions", "greenhouse",
    "albedo", "radiation", "solar", "season", "seasonal", "urban", "elnino", "nino", "nina", "enso", "landslide",
    "erosion", "photosynthesis", "gpp", "ndvi", "evi", "lst", "swe", "biomass", "ecosystem", "biodiversity",
    "earth", "environment", "environmental", "planet", "land", "surface", "water", "hydrology", "hydrological",
    "hotter", "warmer", "colder", "cooler", "wetter", "drier", "dryer", "greener", "rainier", "snowier",
    "polluted", "humid", "sunny", "cloudy", "windy", "stormy", "melting", "thawing", "freezing",
    "desertification", "salinization", "urbanization", "urbanisation", "degradation", "reforestation",
    "afforestation", "sea-level", "sealevel", "tide", "tides", "salinity", "chlorophyll", "upwelling", "reef", "coral",
    # missions / data
    "nasa", "satellite", "modis", "viirs", "airs", "omi", "gpm", "imerg", "merra", "merra2", "gldas", "smap",
    "swot", "seawifs", "giovanni", "appeears", "noaa", "ncei", "reanalysis", "remote", "sensing", "radar",
    "radarsat", "sar", "station", "dataset", "variable", "chlorophyll", "phytoplankton",
    # trend statistics (in scope because the tool teaches them)
    "trend", "trends", "time", "series", "significant", "significance", "mann", "kendall", "sen", "slope",
    "regression", "p-value", "pvalue", "confidence", "interval", "anomaly", "anomalies", "deseasonalize",
    "autocorrelation", "forecast", "projection", "detect", "detection", "change", "changing", "increase",
    "decrease", "rising", "falling", "rate", "decade",
}
EARTH_STEMS = {stem(t) for t in EARTH_TERMS}
STATS_ONLY = {stem(t) for t in ("trend", "time", "series", "significant", "significance", "slope", "regression",
                                "confidence", "interval", "change", "changing", "increase", "decrease", "rising",
                                "falling", "rate", "decade", "detect", "detection", "forecast", "projection")}

OFF_TOPIC_PATTERNS = [
    r"\b(write|generate|debug|fix)\b.*\b(code|program|script|function|app|website|html|css|sql)\b",
    r"\b(python|javascript|java|c\+\+|react|django|leetcode)\b",
    r"\b(poem|song|lyrics|story|joke|essay|rap|novel)\b",
    r"\b(movie|film|actor|actress|celebrity|cricket|football|ipl|nba|fifa|game score|match score)\b",
    r"\b(stock|crypto|bitcoin|share price|investment|loan|salary)\b",
    r"\b(recipe|cook|dating|boyfriend|girlfriend|relationship)\b",
    r"\b(ignore (all|previous|the above) instructions|system prompt|jailbreak|pretend you are)\b",
    r"\b(homework|exam answers?)\b(?!.*\b(climate|rain|temperature|trend|earth)\b)",
]


@dataclass
class GuardResult:
    on_topic: bool
    score: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return {"on_topic": self.on_topic, "score": round(self.score, 3), "reasons": self.reasons}


def check_topic(text: str, catalog_index: BM25 | None = None, threshold: float = 1.0) -> GuardResult:
    t = (text or "").strip()
    if not t:
        return GuardResult(False, 0.0, ["empty question"])
    if len(t) > 2000:
        return GuardResult(False, 0.0, ["question too long (max 2000 characters)"])
    low = t.lower()
    reasons = []
    for pat in OFF_TOPIC_PATTERNS:
        if re.search(pat, low):
            reasons.append(f"off-topic pattern: {pat[:40]}…")
    toks = tokenize(t)
    hits = [w for w in toks if w in EARTH_STEMS]
    earth_hits = [w for w in hits if w not in STATS_ONLY]
    score = 1.0 * len(earth_hits) + 0.35 * (len(hits) - len(earth_hits))
    if catalog_index is not None:
        best = max(catalog_index.scores(t) or [0.0])
        score += min(best / 4.0, 2.0)
        if best > 0:
            reasons.append(f"catalog match {best:.2f}")
    if earth_hits:
        reasons.append(f"earth terms: {', '.join(sorted(set(earth_hits))[:6])}")
    if reasons and any(r.startswith("off-topic") for r in reasons):
        score -= 3.0
    return GuardResult(score >= threshold, score, reasons)


REFUSAL = ("I can only help with Earth-system data: choosing variables (temperature, rainfall, vegetation, "
           "air quality, snow…), regions and periods, and explaining trends and their statistical "
           "significance. Try something like: \"Is rainfall changing in Tamil Nadu since 2001?\"")
