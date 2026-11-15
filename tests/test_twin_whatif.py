import numpy as np
import pandas as pd

from backend.timeseries.model import MonthlySeries, Provenance
from backend.twin.whatif import parse_change, place_result


def test_parse_change_reads_size_unit_direction_and_year():
    c = parse_change("if global temp rises 5 c overall what would be the change in trend for chennai and california")
    assert (c["kind"], c["value"], c["unit"], c["scope"], c["target_year"]) == ("add", 5.0, "°C", "global", None)
    c = parse_change("what if rainfall drops 20% in Kerala by 2050")
    assert (c["kind"], c["value"], c["target_year"]) == ("pct", -20.0, 2050)
    assert parse_change("What if warming in Chennai doubled?")["value"] == 2.0
    assert parse_change("a sudden 2 degree jump in Delhi")["kind"] == "shock"
    assert abs(parse_change("+9F in Texas")["value"] - 5.0) < 1e-9          # °F difference -> °C
    assert parse_change("temperature in Chennai in 2050") is None             # a year is not a change


def _series(trend_per_decade=0.2):
    t = pd.date_range("1996-01-01", "2025-12-01", freq="MS")
    rng = np.random.default_rng(1)
    y = 28 + 2 * np.sin(2 * np.pi * (t.month - 1) / 12) + trend_per_decade / 120 * np.arange(len(t)) + rng.normal(0, .3, len(t))
    prov = Provenance(source_api="test", variable="T2M", geometry={}, dataset_short_name="M2TMNXSLV", version="5.12.4")
    return MonthlySeries(time=t, value=y, units="°C", provenance=prov, label="t2m")


def test_place_result_adds_exactly_the_change_by_the_target_year():
    r = place_result("Air temperature", "Chennai", _series(), parse_change("+5 c"), 2100)
    assert r["label"] == "simulated" and r["simulated"]["years"][-1] == 2100
    assert abs(r["end"]["difference"] - 5.0) < 0.05                          # same noise in both runs
    h = 2100 - 2025
    assert abs(r["trend_per_decade"]["with_change"] - (r["trend_per_decade"]["observed"] + 5 / (h / 10))) < 1e-3
    assert len(r["observed"]["years"]) == 30 and r["provenance"]["dataset"] == "M2TMNXSLV"
    lo, hi = r["end"]["with_change_range90"]
    assert lo < r["end"]["with_change"] < hi
    assert "prediction" not in r["plain_language"].lower()
