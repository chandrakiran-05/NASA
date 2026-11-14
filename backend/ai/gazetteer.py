"""Offline place lookup (no network): GeoNames cities >15k population + countries + US states
(geonamescache package) + the archetype example regions.

Cities become a point plus a default buffer box; countries and US states become an approximate
bbox from the extent of their cities (users can adjust the box on the map). Oceans, seas, lakes,
rivers, deserts, ranges and other large features come from the editorial presets.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from ..core.geometry import Region, point_buffer

COMMON_WORDS = set("""
rain snow ice heat cold warm hot dry wet green blue red white black gold silver most best nice mobile reading bath
split of the and or for from with march may june july august date university college school temperature trend
trends climate data change ocean sea lake river forest desert city town north south east west central island
delta valley mountain plain plains coast bay gulf cape port fort mount saint san santa victoria union
""".split())


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()


# a name next to one of these words is a water body or landform, not the city/state of that name
# ("Lake Victoria", "Colorado River", "Gulf of Guinea"); without a preset for it we report no place
FEATURE_AFTER = set("river rivers basin sea ocean gulf bay lake delta strait straits dam reservoir desert mountains "
                    "range glacier reef current canal plateau".split())
FEATURE_BEFORE = set("lake gulf bay sea strait straits river mount".split())

PRESETS = Path(__file__).resolve().parents[1] / "catalog" / "data" / "region_presets.json"


@lru_cache(maxsize=1)
def _index() -> dict:
    import geonamescache
    gc = geonamescache.GeonamesCache()
    cities = gc.get_cities()
    countries = gc.get_countries()
    idx: dict[str, dict] = {}
    by_cc: dict[str, list[tuple[float, float]]] = {}
    by_state: dict[str, list[tuple[float, float]]] = {}
    for c in cities.values():
        by_cc.setdefault(c["countrycode"], []).append((c["longitude"], c["latitude"]))
        if c["countrycode"] == "US":
            by_state.setdefault(c.get("admin1code"), []).append((c["longitude"], c["latitude"]))
        rec = {"type": "city", "name": c["name"], "lat": c["latitude"], "lon": c["longitude"],
               "country": c["countrycode"], "population": c["population"]}
        k = _fold(c["name"])
        if len(k) >= 3 and (k not in idx or idx[k].get("population", 0) < rec["population"]):
            idx[k] = rec
        # alternate (exonym) names: only Latin script, and flagged so lowercase text must not match them
        for a in c.get("alternatenames", []):
            if not a or not all(ord(ch) < 0x250 for ch in a):
                continue
            ka = _fold(a)
            if len(ka) < 4 or ka == k:
                continue
            alt = dict(rec, alternate=True)
            if ka not in idx or (idx[ka].get("alternate") and idx[ka].get("population", 0) < rec["population"]):
                idx[ka] = alt
    for cc, co in countries.items():
        pts = by_cc.get(cc)
        if not pts:
            continue
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        pad = 0.5
        rec = {"type": "country", "name": co["name"], "iso": cc,
               "bbox": [max(min(lons) - pad, -180), max(min(lats) - pad, -90),
                        min(max(lons) + pad, 180), min(max(lats) + pad, 90)],
               "approximate": True, "population": co.get("population", 0) * 10}
        idx[_fold(co["name"])] = rec
    for st in gc.get_us_states().values():
        k = _fold(st["name"])
        rec = {"type": "us_state", "name": st["name"], "code": st["code"], "population": 10 ** 7}
        pts = by_state.get(st["code"])
        if pts:   # approximate box from the extent of the state's cities, like countries
            lons, lats = [p[0] for p in pts], [p[1] for p in pts]
            rec.update(bbox=[max(min(lons) - 0.3, -180), min(lats) - 0.3, min(max(lons) + 0.3, 180), max(lats) + 0.3],
                       approximate=True)
        idx.setdefault(k, rec)
    # editorial region presets win over everything (states, basins, deserts)
    for r in json.loads(PRESETS.read_text(encoding="utf-8"))["regions"]:
        rec = {"type": "region", "name": r["name"], "bbox": r["bbox"], "approximate": True, "population": 10 ** 9,
               "kind": r.get("kind", "land"), **({"note": r["note"]} if r.get("note") else {})}
        for n in [r["name"], *r.get("aliases", [])]:
            kk = _fold(n)
            if len(kk) >= 3:
                idx[kk] = rec
    return idx


def lookup(name: str) -> dict | None:
    return _index().get(_fold(name))


def find_places(text: str, max_n: int = 3) -> list[dict]:
    """Find place mentions in free text (longest n-gram first)."""
    idx = _index()
    text = re.sub(r"['’]s\b", "", text)          # possessive: "Australia's wheat belt"
    raw_tokens = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]*", text)
    tokens = [_fold(t) for t in raw_tokens]
    used = [False] * len(tokens)
    found = []
    for n in (4, 3, 2, 1):
        for i in range(len(tokens) - n + 1):
            if any(used[i:i + n]):
                continue
            k = " ".join(tokens[i:i + n]).strip()
            if not k or k not in idx:
                continue
            rec = idx[k]
            capitalised = all(raw_tokens[j][:1].isupper() for j in range(i, i + n))
            if n == 1 and k in COMMON_WORDS and not capitalised:
                continue
            if rec["type"] == "city" and rec.get("alternate") and not capitalised:
                continue
            if rec["type"] == "city" and not capitalised and rec["population"] < 100_000:
                continue
            if rec["type"] != "region" and (
                    (i + n < len(tokens) and tokens[i + n] in FEATURE_AFTER)
                    or (i >= 1 and tokens[i - 1] in FEATURE_BEFORE)
                    or (i >= 2 and tokens[i - 1] == "of" and tokens[i - 2] in FEATURE_BEFORE)):
                continue
            for j in range(i, i + n):
                used[j] = True
            found.append(dict(rec, matched=" ".join(raw_tokens[i:i + n])))
    order = {t: i for i, t in enumerate(tokens)}
    found.sort(key=lambda r: order.get(_fold(r["matched"]).split(" ")[0], 0))   # keep text order
    return found[:max_n]


def place_to_region(rec: dict, city_radius_km: float = 25.0, as_point: bool = False) -> Region | None:
    if rec["type"] == "city":
        if as_point:
            return Region("point", (rec["lon"], rec["lat"], rec["lon"], rec["lat"]),
                          point=(rec["lon"], rec["lat"]), name=rec["name"])
        return point_buffer(rec["lon"], rec["lat"], city_radius_km, name=rec["name"])
    if rec.get("bbox"):
        return Region("bbox", tuple(rec["bbox"]), name=rec["name"])
    return None
