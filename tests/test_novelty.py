"""Team novelty spec (docs/06-feature-spec.md) F1-F5 + Trend Scan, and NASA-tutorial format fixes."""
import asyncio
import warnings
from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.novelty.agreement import product_agreement, second_opinions
from backend.novelty.court import court
from backend.novelty.evidence_clock import evidence_clock
from backend.novelty.integrity import integrity_audit, pettitt, trend_or_jump
from backend.novelty.nulls import null_lineup
from backend.timeseries.model import MonthlySeries, Provenance
from backend.timeseries.parsers import parse_giovanni_timeseries_csv
from tests.conftest import wait_job

warnings.filterwarnings("ignore")
IDX = pd.date_range("2001-01-01", periods=288, freq="MS")
T = np.arange(288) / 12
SEAS = 5 * np.sin(2 * np.pi * IDX.month.to_numpy() / 12)


def ar(phi, sd, seed, n=288):
    rng = np.random.default_rng(seed)
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = phi * e[i - 1] + rng.normal(0, sd)
    return e


def ms(y, *, short="X", retrieved="2026-11-01T00:00:00+00:00", units="degC", label="x", product=None):
    p = Provenance("test", "var", {}, dataset_short_name=short, retrieved_at=retrieved, product_id=product)
    return MonthlySeries(IDX[:len(y)], np.asarray(y, float), units, p, label=label)


def des(m):
    from backend.analysis.deseason import deseasonalize
    return deseasonalize(m, "stl").deseasonalized


# ---------------------------------------------------------------- F1
def test_integrity_zero_block_is_not_fit():
    y = 20 + SEAS + 0.03 * T + ar(0.3, 0.3, 1)
    y[100:110] = 0.0
    m = ms(y)
    a = integrity_audit(m, des(m))
    assert a["badge"] == "NOT_FIT"
    assert any(f["type"] == "zero_run" and f["months"] == 10 for f in a["flags"])


def test_integrity_imerg_seam_step_detected():
    y = 4 + SEAS * 0.5 + ar(0.2, 0.3, 2)
    y[IDX >= "2014-06-01"] += 1.5                       # planted step at the TRMM->GPM seam
    m = ms(y, short="GPM_3IMERGM", units="mm/day")
    a = integrity_audit(m, des(m))
    seam = next(s for s in a["seams"] if s["event"] == "imerg-trmm-gpm")
    assert seam["significant"] and seam["step"] == pytest.approx(1.5, abs=0.4)
    assert a["badge"] in ("CAUTION", "NOT_FIT")
    assert a["trend_or_jump"]["best_model"] in ("jump", "trend_plus_jump")
    assert any("Possible instrument effect" in r for r in a["reasons"])


def test_integrity_clean_series_ok_and_retrieved_before_fix():
    y = 20 + SEAS + 0.03 * T + ar(0.3, 0.3, 3)
    m = ms(y)
    assert integrity_audit(m, des(m))["badge"] == "OK"
    old = ms(y, short="M2T1NXSLV", retrieved="2026-01-10T00:00:00+00:00")
    a = integrity_audit(old, des(old))
    assert a["badge"] == "NOT_FIT" and any(f["type"] == "retrieved_before_fix" for f in a["flags"])


def test_pettitt_matches_bruteforce_and_trend_or_jump():
    rng = np.random.default_rng(4)
    y = np.r_[rng.normal(0, 1, 80), rng.normal(2, 1, 80)]
    r = pettitt(y)
    n = len(y)
    U = [sum(np.sign(y[j] - y[i]) for i in range(t) for j in range(t, n)) for t in range(1, n)]
    assert r["K"] == pytest.approx(max(abs(u) for u in U))
    assert r["p"] < 0.001 and abs(r["index_valid"] - 80) <= 3
    idx = pd.date_range("2001-01-01", periods=n, freq="MS")
    assert trend_or_jump(np.arange(n) / 12, y, idx)["best_model"] in ("jump", "trend_plus_jump")
    yt = 0.3 * np.arange(n) / 12 + rng.normal(0, 0.3, n)
    assert trend_or_jump(np.arange(n) / 12, yt, idx)["best_model"] == "trend"


# ---------------------------------------------------------------- F3
def test_court_on_strong_trend_and_on_persistent_noise():
    c = court(ms(20 + SEAS + 0.06 * T + ar(0.3, 0.3, 5)))
    assert c["stamp"] == "SIGNIFICANT" and c["diagnostics"]["seasonal"]
    assert {j["id"] for j in c["jurors"]} >= {"ols_naive", "ols_ar1", "mk_original", "mk_tfpw", "mk_hamed_rao",
                                              "mk_ess_ar1", "seasonal_mk", "sen_ci"}
    flipped = 0
    for s in range(30):
        c2 = court(ms(20 + SEAS + ar(0.8, 0.4, 100 + s)))
        ign = next(x for x in c2["cross_examination"] if x["id"] == "ignore_autocorrelation")
        flipped += c2["stamp"] == "NOT PROVEN" and ign["significant"]
        assert c2["diagnostics"]["lag1_significant"]
    assert flipped >= 3            # naive tests 'find' trends in pure persistent noise; the court does not


# ---------------------------------------------------------------- F5
def test_nulls_permutation_p_and_lineup():
    strong = null_lineup(ms(20 + SEAS + 0.08 * T + ar(0.3, 0.3, 6)), n_null=500)
    assert strong["perm_p"] < 0.01
    assert len(strong["lineup"]["panels"]) == 20
    none = null_lineup(ms(20 + SEAS + ar(0.3, 0.3, 7)), n_null=500)
    assert none["perm_p"] > 0.05
    again = null_lineup(ms(20 + SEAS + ar(0.3, 0.3, 7)), n_null=500)
    assert again["perm_p"] == none["perm_p"]                 # fixed seed -> reproducible
    assert "Simulated" in none["label"]


# ---------------------------------------------------------------- F2
def test_evidence_clock_expanding_rank_and_cant_tell():
    c = evidence_clock(ms(20 + SEAS + 0.04 * T + ar(0.3, 0.3, 8)), start=2010, end=2019)
    assert c["expanding"][0]["end_year"] == 2010 and c["expanding"][-1]["end_year"] == 2024
    assert c["window_rank"]["length_years"] == 10 and 1 <= c["window_rank"]["rank_from_lowest"] <= c["window_rank"]["n_windows"]
    flat = evidence_clock(ms(20 + SEAS + ar(0.3, 0.3, 9) + 1e-6 * T))
    assert flat["years_to_detect"]["status"] in ("cant_tell", "needs_more_data", "detectable")
    assert "exploratory" in c["triangle_label"]


# ---------------------------------------------------------------- F4
def test_product_agreement_robust_and_disputed():
    a = ms(20 + SEAS + 0.05 * T + ar(0.3, 0.3, 10), label="model")
    b = ms(19 + SEAS + 0.05 * T + ar(0.3, 0.3, 11), label="satellite")
    assert product_agreement(a, b)["badge"] == "ROBUST"
    c = ms(19 + SEAS - 0.05 * T + ar(0.3, 0.3, 12), label="station")
    d = product_agreement(a, c)
    assert d["badge"] == "DISPUTED" and d["difference"]["significant"]
    assert "station_tavg" in second_opinions("merra2_t2m")["same_quantity"]


# ---------------------------------------------------------------- NASA format fixes
NASA_TUTORIAL_CSV = "\n".join(
    ["prod_name,GLDAS_NOAH025_3H_2_1", "param_short_name,Tair_f_inst", "param_name,Near surface air temperature",
     "unit,K", "begin_time,2000-01-01T03:00:00", "end_time,2000-01-01T12:00:00", "lat,45.125", "lon,-98.125",
     "request_lat,45.125", "request_lon,-98.125", "fill_value,-9999.0", "shape,point", "dataset,GLDAS",
     "", "Timestamp (UTC),Near surface air temperature",
     "2000-01-01T03:00:00,274.663", "2000-01-01T06:00:00,271.324", "2000-01-01T09:00:00,-9999.0"])


def test_parser_reads_nasa_tutorial_layout():
    hdr, t, v = parse_giovanni_timeseries_csv(NASA_TUTORIAL_CSV)
    assert hdr["param_name"] == "Near surface air temperature" and hdr["unit"] == "K"
    assert v[0] == 274.663 and np.isnan(v[2]) and len(t) == 3


def test_quota_guard_falls_back_to_opendap(settings, fake):
    from backend.catalog.catalog import load_catalog
    from backend.core.geometry import parse_geometry
    from backend.core.http import ResilientHTTP
    from backend.connectors.giovanni import GiovanniPoint
    from backend.storage.db import Database
    from backend.storage.series_store import SeriesStore
    from backend.timeseries.service import TimeSeriesService
    from tests.fakes import transport
    GiovanniPoint._quota_cache.update(t=0.0, value=None)
    fake.quota = 0.97
    svc = TimeSeriesService(settings, ResilientHTTP(settings, transport=transport(fake)), load_catalog(),
                            SeriesStore(settings.series_dir, Database(settings.db_path)))
    out = asyncio.run(svc.build_series("imerg_precip_monthly", parse_geometry({"type": "Point", "coordinates": [80.27, 13.08]}),
                                       date(2001, 1, 1), date(2003, 12, 31)))
    assert out["source_api"] == "cloud_opendap"
    assert "quota" in out["attempts"][0]["error"]
    GiovanniPoint._quota_cache.update(t=0.0, value=None)


def test_token_from_earthaccess_when_only_password(settings, monkeypatch):
    import earthaccess

    from backend.core import auth
    settings.earthdata_token = None
    auth._TOKEN_CACHE.clear()
    monkeypatch.setattr(earthaccess, "login", lambda **kw: True)
    monkeypatch.setattr(earthaccess, "get_edl_token", lambda: {"access_token": "tok-from-earthaccess"})
    assert auth.edl_bearer_headers(settings) == {"Authorization": "Bearer tok-from-earthaccess"}
    auth._TOKEN_CACHE.clear()


# ---------------------------------------------------------------- API
def test_novelty_endpoints_and_scan(client):
    from tests.test_api import make_series
    sid = make_series(client)
    a = client.post("/api/analyze", json={"series_id": sid, "include_series": False}).json()
    assert a["court"]["stamp"] in ("SIGNIFICANT", "NOT PROVEN")
    assert client.get(f"/api/timeseries/{sid}/integrity").json()["badge"] in ("OK", "CAUTION", "NOT_FIT")
    assert client.get(f"/api/analyze/{sid}/court").json()["jurors"]
    clk = client.get(f"/api/analyze/{sid}/detectability", params={"start": 2005, "end": 2014}).json()
    assert clk["window_rank"]["length_years"] == 10
    nl = client.post("/api/analyze/nulls", json={"series_id": sid, "n_null": 200}).json()
    assert len(nl["null_slopes_per_decade"]) == 200
    sid2 = make_series(client, variable="imerg_precip_daily")
    pa = client.post("/api/compare", json={"series_ids": [sid, sid2], "mode": "product_agreement"}).json()
    assert pa["badge"] in ("ROBUST", "DISPUTED", "INCONCLUSIVE")
    assert client.get("/api/variables/imerg_precip_monthly/second-opinions").json()["group"] == "precipitation"
    r = client.post("/api/scan", json={"geometry": {"type": "Point", "coordinates": [80.27, 13.08]},
                                       "start": "2001-01", "end": "2004-12",
                                       "variable_ids": ["merra2_t2m", "imerg_precip_monthly", "modis_ndvi_monthly"]})
    j = wait_job(client, r.json()["job_id"], 60)
    assert j["status"] == "done", j
    assert len(j["result"]["ranking"]) == 3 and "coherence" in j["result"]
