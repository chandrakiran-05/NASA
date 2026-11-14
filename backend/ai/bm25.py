"""Tiny offline BM25 (Okapi) index with light stemming and synonym expansion.

Used for: catalog search (/api/variables?q=...), grounding the offline LLM (retrieval),
and the Earth-topic guardrail score. No model download, microsecond queries.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9₀-₉]+")
STOP = set("""a an the of in on at to for from by with and or is are was were be been it its this that these those
what which who whom how why where when do does did can could should would will shall may might my our your their
me we you they i about over under into than then there here as if not no yes very much many more most less least
show tell give find please want like get look see""".split())

# words that describe the *question*, not the quantity; ignored when ranking variables
QUERY_STOP = set("""compare comparison versus vs trend trends change changes changing changed data over year years
since become becoming getting get got going region area place time period last past recent recently between
increase increasing decrease decreasing rising falling up down much more less test significant""".split())

SYNONYMS = {
    "rainfall": ["precipitation", "rain"], "rain": ["precipitation", "rainfall"], "precip": ["precipitation"],
    "warming": ["temperature", "heat"], "hot": ["temperature", "heat"], "heat": ["temperature"],
    "greenness": ["ndvi", "vegetation"], "greening": ["ndvi", "vegetation"], "trees": ["forest", "vegetation"],
    "deforestation": ["forest", "vegetation", "ndvi"], "pollution": ["no2", "aerosol", "air"],
    "smog": ["no2", "aerosol", "pollution"], "dust": ["aerosol"], "smoke": ["aerosol", "fire"],
    "drought": ["soil", "moisture", "precipitation", "dry"], "dry": ["drought", "moisture"],
    "flood": ["runoff", "precipitation"], "flooding": ["runoff", "precipitation"],
    "snowpack": ["snow", "swe"], "glacier": ["snow", "swe", "mountain"], "humid": ["humidity"],
    "evaporation": ["evapotranspiration"], "et": ["evapotranspiration"], "crops": ["agriculture", "vegetation"],
    "uv": ["ozone", "ultraviolet"], "co2": ["carbon"], "monsoon": ["precipitation", "rain"],
    "city": ["urban"], "urban": ["city"], "temp": ["temperature"],
    "hotter": ["temperature", "heat"], "warmer": ["temperature"], "colder": ["temperature"],
    "cooler": ["temperature"], "wetter": ["precipitation", "rain"], "rainier": ["precipitation", "rain"],
    "drier": ["drought", "precipitation", "moisture"], "dryer": ["drought", "precipitation", "moisture"],
    "greener": ["ndvi", "vegetation", "greening"], "green": ["ndvi", "vegetation"],
    "polluted": ["pollution", "no2", "aerosol"], "cleaner": ["pollution", "no2"], "snowier": ["snow"],
    "melting": ["snow", "swe"], "air": ["air"], "quality": ["pollution", "no2"],
}


def stem(w: str) -> str:
    """Very light English stemmer; the same function is used for documents and queries."""
    if len(w) <= 4:
        return w
    for suf in ("ations", "ation", "ings", "ing", "ness"):
        if w.endswith(suf) and len(w) > len(suf) + 3:
            return w[: -len(suf)]
    if w.endswith("ies") and len(w) > 5:
        return w[:-3] + "y"
    if w.endswith(("sses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if w.endswith("ed") and len(w) > 5:
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokenize(text: str, expand: bool = False) -> list[str]:
    toks = [t for t in _TOKEN.findall((text or "").lower().replace("₂", "2")) if t not in STOP]
    out = []
    for t in toks:
        out.append(stem(t))
        if expand:
            out.extend(stem(s) for s in SYNONYMS.get(t, []))
    return out


QUERY_STOP_STEMS = {stem(w) for w in QUERY_STOP}


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75, drop_question_words: bool = True):
        self.k1, self.b = k1, b
        self.drop = QUERY_STOP_STEMS if drop_question_words else set()
        self.docs_tokens = [tokenize(d) for d in docs]
        self.doc_len = [len(d) for d in self.docs_tokens]
        self.avgdl = (sum(self.doc_len) / len(self.doc_len)) if docs else 0.0
        self.tf = [Counter(d) for d in self.docs_tokens]
        df = Counter()
        for d in self.docs_tokens:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.vocab = set(df)

    def scores(self, query: str) -> list[float]:
        q = [t for t in tokenize(query, expand=True) if t not in self.drop]
        out = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            dl = self.doc_len[i] or 1
            for t in q:
                f = tf.get(t)
                if not f:
                    continue
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out

    def top(self, query: str, k: int = 5, min_score: float = 0.0) -> list[tuple[int, float]]:
        sc = self.scores(query)
        ranked = sorted(((i, s) for i, s in enumerate(sc) if s > min_score), key=lambda x: -x[1])
        return ranked[:k]

    def coverage(self, query: str) -> float:
        """Fraction of query tokens known to the index (used by the topic guardrail)."""
        q = tokenize(query, expand=False)
        if not q:
            return 0.0
        return sum(1 for t in q if t in self.vocab) / len(q)
