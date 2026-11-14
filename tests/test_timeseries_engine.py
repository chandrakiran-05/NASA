import numpy as np
import pandas as pd
import pytest

from backend.timeseries.model import Provenance, RawSeries, ValueMeta
from backend.timeseries.parsers import (parse_appeears_point_csv, parse_cdo_json, parse_configured_variables,
                                        parse_giovanni_timeseries_csv, parse_harmony_area_csv, parse_ncei_ads_json,
                                        split_giovanni_id)
from backend.timeseries.qc import apply_qc
from backend.timeseries.resample import to_monthly

P = Provenance("test", "x", {})


def test_giovanni_csv_header_detection_and_fill():
    txt = "\n".join(["prod_name,M2T1NXSLV_5_12_4", "param_name,T2M", "unit,K", "lat,13.0", "lon,80.0",
                     "fill_value,-9999", ",", "Timestamp (UTC),T2M",
                     "2001-01-01T00:00:00,300.5", "2001-01-01T01:00:00,-9999", "2001-01-01T02:00:00,301.0"])
    hdr, t, v = parse_giovanni_timeseries_csv(txt)
    assert hdr["unit"] == "K" and hdr["param_name"] == "T2M"
    assert len(t) == 3 and np.isnan(v[1]) and v[2] == 301.0


def test_harmony_csv():
    txt = "collection,C1\nvariable,T2M\nunits,K\n,\ntime,mean_T2M\n2001-01-01,290.1\n2001-02-01,291.2\n"
    hdr, t, v = parse_harmony_area_csv(txt)
    assert hdr["units"] == "K" and list(v) == [290.1, 291.2]


def test_appeears_csv_and_ncei_and_cdo():
    csv = ("ID,Latitude,Longitude,Date,MOD13A3_061__1_km_monthly_NDVI,MOD13A3_061__1_km_monthly_pixel_reliability\n"
           "p1,13,80,2001-01-01,0.45,0\np1,13,80,2001-02-01,0.50,3\n")
    t, v, qc = parse_appeears_point_csv(csv, "MOD13A3.061", "_1_km_monthly_NDVI", "p1",
                                        "MOD13A3_061__1_km_monthly_pixel_reliability")
    assert list(v) == [0.45, 0.50] and list(qc) == [0, 3]
    t, v, st = parse_ncei_ads_json('[{"DATE":"2000-01","STATION":"A","TAVG":" 1.5"},{"DATE":"2000-02","STATION":"A","TAVG":""}]', "TAVG")
    assert v[0] == 1.5 and np.isnan(v[1]) and str(t[0])[:10] == "2000-01-01"
    t, v = parse_cdo_json([{"results": [{"date": "2000-01-01T00:00:00", "datatype": "TAVG", "value": 2.0},
                                        {"date": "2000-01-01T00:00:00", "datatype": "PRCP", "value": 9.0}]}], "TAVG")
    assert list(v) == [2.0]


def test_giovanni_id_split_and_listing_parser():
    assert split_giovanni_id("GLDAS_NOAH025_3H_2_1_Tair_f_inst") == {
        "id": "GLDAS_NOAH025_3H_2_1_Tair_f_inst", "short_name": "GLDAS_NOAH025_3H", "version": "2.1",
        "variable": "Tair_f_inst"}
    assert split_giovanni_id("GPM_3IMERGM_07_precipitation")["short_name"] == "GPM_3IMERGM"
    assert parse_configured_variables({"variables": [{"id": "M2T1NXSLV_5_12_4_T2M"}, {"id": "junk"}]}) == \
        ["M2T1NXSLV_5_12_4_T2M"]
    assert parse_configured_variables(["OMTO3d_003_ColumnAmountO3"]) == ["OMTO3d_003_ColumnAmountO3"]


def test_qc_scaling_autodetect_fill_range_and_flags():
    raw_units = np.array([4500, -3000, 12000, 6000], float)           # raw ints, one fill, one out of range
    rs = RawSeries(pd.date_range("2001-01-01", periods=4, freq="MS"), raw_units, "monthly", P,
                   ValueMeta(fill_values=(-3000,), scale_factor=0.0001, valid_min=-2000, valid_max=10000),
                   qc_pass=np.array([True, True, True, False]))
    out, rep = apply_qc(rs)
    assert out.value[0] == pytest.approx(0.45)
    assert np.isnan(out.value[1]) and np.isnan(out.value[2]) and np.isnan(out.value[3])
    assert rep["n_fill"] == 1 and rep["n_out_of_range"] == 1 and rep["n_bad_quality_flag"] == 1
    # already-scaled values (AppEEARS CSV) are detected and not scaled twice
    rs2 = RawSeries(pd.date_range("2001-01-01", periods=3, freq="MS"), np.array([0.45, 0.5, -0.3]), "monthly", P,
                    ValueMeta(fill_values=(-3000,), scale_factor=0.0001, valid_min=-2000, valid_max=10000))
    out2, rep2 = apply_qc(rs2)
    assert rep2["scaling_autodetected"] is True
    assert out2.value[0] == pytest.approx(0.45) and np.isnan(out2.value[2])


def test_daily_to_monthly_completeness_rule():
    t = pd.date_range("2001-01-01", "2001-03-31", freq="D")
    v = np.ones(len(t))
    v[(t.month == 2) & (t.day > 10)] = np.nan              # Feb has 10/28 valid days < 70%
    ms = to_monthly(RawSeries(t, v, "daily", P), min_valid_fraction=0.7)
    assert list(np.isnan(ms.value)) == [False, True, False]
    assert ms.n_obs.tolist() == [31, 10, 31]


def test_hourly_to_monthly():
    t = pd.date_range("2001-01-01", "2001-02-28 23:00", freq="h")
    ms = to_monthly(RawSeries(t, np.where(t.month == 1, 10.0, 20.0), "hourly", P))
    assert ms.value.tolist() == [10.0, 20.0]


def test_8day_composites_day_weighted_and_clipped_at_year_end():
    starts = pd.DatetimeIndex(["2001-01-01", "2001-01-09", "2001-01-17", "2001-01-25", "2001-02-02", "2001-12-27"])
    vals = np.array([1.0, 1.0, 1.0, 5.0, 5.0, 9.0])
    ms = to_monthly(RawSeries(starts, vals, "8-day", P), start="2001-01-01", end="2001-12-31",
                    min_valid_fraction=0.0)
    jan = (24 * 1 + 7 * 5) / 31                            # 25 Jan composite covers 25-31 Jan (7 days)
    assert ms.value[0] == pytest.approx(jan)
    assert ms.n_obs[11] == 5                               # 27-31 Dec only: clipped at year end
    assert len(ms.value) == 12


def test_monthly_index_is_regular_with_nan_gaps():
    t = pd.DatetimeIndex(["2001-01-01", "2001-04-01"])
    ms = to_monthly(RawSeries(t, np.array([1.0, 2.0]), "monthly", P), start="2001-01-01", end="2001-06-30")
    assert len(ms.time) == 6 and np.isnan(ms.value[1:3]).all() and np.isnan(ms.value[4:]).all()
