"""The challenge's resource paper, as data: regions (Table 1) and published results (Table 4).

Acker, McMahon, Shen, Hearty, Casey: "Time-Series Analysis of Remotely-Sensed SeaWiFS Chlorophyll in
River-Influenced Coastal Regions". NASA NTRS 20090042747.
"""
from __future__ import annotations

PAPER = {
    "title": "Time-Series Analysis of Remotely-Sensed SeaWiFS Chlorophyll in River-Influenced Coastal Regions",
    "authors": "Acker, J. G., McMahon, E., Shen, S., Hearty, T., Casey, N.",
    "ntrs_id": "20090042747",
    "url": "https://ntrs.nasa.gov/citations/20090042747",
    "citation": ("Acker, J. G., McMahon, E., Shen, S., Hearty, T., Casey, N. Time-Series Analysis of Remotely-Sensed "
                 "SeaWiFS Chlorophyll in River-Influenced Coastal Regions. NASA Technical Reports Server, "
                 "NTRS 20090042747. https://ntrs.nasa.gov/citations/20090042747"),
    "data": "SeaWiFS Level-3 monthly chlorophyll a, 9 km; Giovanni area-averaged (arithmetic mean) monthly series",
    "period": {"start": "1998-01", "end": "2007-12"},
    "boxes": "0.5 x 0.5 degree boxes offshore of river mouths, chosen where mean chl a is at most 1 mg m-3",
    "method": ["least-squares linear regression on the complete monthly series",
               "ANOVA F-test, significant when p < 0.05; R-squared reported",
               "yearly anomalies: subtract each calendar month's mean, average the monthly anomalies per year, "
               "regress those"],
    "conclusion": ("The paper reports no significant trend for rivers with low human impact, significant negative "
                   "trends for most human-impacted rivers, and the Pearl River as the positive exception."),
    "caveat": ("Chlorophyll a retrieved near river mouths can be biased by coloured dissolved organic matter (CDOM) "
               "and suspended sediment (the paper's own caveat)."),
    "footnotes": {"*": "Includes all annual data.", "**": "Includes October-December 2000 data."},
}

# (id, name, north, south, west, east, distance_km, p, F, slope_per_month, r2, mean, footnote)
_ROWS = [
    ("amazon", "Amazon", 8.0, 7.5, -51.0, -50.5, 850, 0.78, 0.07, -0.0005, 0.0006, 0.55, None),
    ("congo", "Congo", -5.0, -5.5, 2.0, 2.5, 1100, 0.28, 1.17, -0.0023, 0.0099, 0.728, None),
    ("eel", "Eel", 41.5, 41.0, -125.9, -125.4, 150, 0.035, 4.53, 0.0017, 0.0371, 0.64, "*"),
    ("ganges", "Ganges", 20.3, 19.8, 89.4, 89.9, 275, 0.03, 4.8, -0.001, 0.0402, 0.35, None),
    ("guadalquivir", "Guadalquivir", 36.5, 36.0, -6.8, -6.3, 65, 0.07, 3.28, -0.0024, 0.027, 0.70, None),
    ("mississippi_east", "Mississippi (East)", 29.6, 29.1, -86.75, -86.25, 300, 0.0169, 5.66, -0.0014, 0.0458, 0.38,
     None),
    ("mississippi_west", "Mississippi (West)", 28.75, 28.25, -94.0, -93.5, 300, 0.0018, 10.12, -0.0043, 0.079, 0.54,
     None),
    ("orinoco", "Orinoco", 12.5, 12.0, -64.8, -64.3, 700, 0.63, 0.23, -0.0005, 0.002, 0.66, None),
    ("pearl", "Pearl", 22.5, 22.0, 117.5, 118.0, 400, 0.068, 3.37, 0.0006, 0.0289, 0.30, None),
    ("po", "Po", 44.5, 44.0, 13.5, 14.0, 150, 0.053, 3.8, -0.0012, 0.0313, 0.39, "**"),
]

# The paper also analysed the Po without its October-December 2000 flood spike.
EXCLUSIONS = {"po": {"start": "2000-10", "end": "2000-12", "label": "excluding the Oct-Dec 2000 flood spike"}}

RIVERS = [
    {"id": i, "name": nm, "box": {"north": n, "south": s, "west": w, "east": e},
     "bbox": [w, s, e, n], "centre": [(w + e) / 2, (s + n) / 2],
     "published": {"distance_km": d, "p": p, "F": F, "slope_per_month": b, "slope_per_decade": b * 120,
                   "r2": r2, "mean": mu, "units": "mg m-3", "significant": p < 0.05, "footnote": fn,
                   "footnote_text": PAPER["footnotes"].get(fn) if fn else None}}
    for i, nm, n, s, w, e, d, p, F, b, r2, mu, fn in _ROWS
]
BY_ID = {r["id"]: r for r in RIVERS}
