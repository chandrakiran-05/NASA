"""Tests on REAL official responses recorded live from NASA/NOAA on 2026-11-14 (tests/fixtures/recorded)."""
from pathlib import Path

import numpy as np

from backend.analysis.deseason import deseasonalize
from backend.novelty.integrity import integrity_audit
from backend.timeseries.model import Provenance, RawSeries, ValueMeta
from backend.timeseries.parsers import parse_ncei_ads_json
from backend.timeseries.resample import to_monthly

REC = Path(__file__).parent / "fixtures" / "recorded"


def test_real_noaa_chennai_station_parses_and_is_flagged_not_fit():
    raw = (REC / "ncei_gsom_IN020040900_1981_2024.json").read_text()
    t, v, st = parse_ncei_ads_json(raw, "TAVG")
    assert set(st) == {"IN020040900"} and np.nanmax(v) < 40 and np.nanmin(v) > 20     # Chennai monthly means, degC
    ms = to_monthly(RawSeries(t, v, "monthly", Provenance("ncei.ads", "TAVG", {}), ValueMeta(units="degC")),
                    start="1981-01-01", end="2024-12-31")
    assert ms.n == 528 and ms.n_valid == 89
    assert integrity_audit(ms, deseasonalize(ms, "climatology").deseasonalized)["badge"] == "NOT_FIT"


def test_real_giovanni_listing_contains_every_catalog_id():
    from backend.catalog.catalog import load_catalog
    from backend.timeseries.parsers import parse_configured_variables
    ids = set(parse_configured_variables((REC / "giovanni_configured_variables.json").read_text()))
    assert len(ids) > 700
    for v in load_catalog().variables.values():
        for k in ("giovanni_id", "giovanni_point_id"):
            if v.get(k):
                assert v[k] in ids, v[k]
