"""Request bodies (pydantic v2). Responses are plain JSON documented in docs/API.md."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..analysis.engine import ALL_METHODS
from ..insights.engine import ALL_INSIGHTS


class TimeseriesRequest(BaseModel):
    variable_id: str = Field(..., examples=["merra2_t2m"])
    geometry: dict = Field(..., examples=[{"type": "Point", "coordinates": [80.27, 13.08]}],
                           description="GeoJSON Point/Polygon, or {type: 'BBox', bbox: [w,s,e,n]}")
    start: str = Field(..., examples=["2001-01"], description="YYYY, YYYY-MM or YYYY-MM-DD")
    end: str = Field(..., examples=["2024-12"])
    options: dict = Field(default_factory=dict, description="stations, max_stations, min_valid_fraction")
    refresh: bool = False


class UploadSeries(BaseModel):
    time: list[str]
    value: list[float | None]
    units: str | None = None
    label: str | None = None

    @field_validator("value")
    @classmethod
    def same_len(cls, v, info):
        t = info.data.get("time")
        if t is not None and len(t) != len(v):
            raise ValueError("time and value must have the same length")
        return v


class AnalyzeRequest(BaseModel):
    series_id: str
    alpha: float = Field(0.05, gt=0, lt=0.5)
    deseasonalize: bool | Literal["stl", "climatology", "none"] = True
    methods: list[Literal["ols", "mk", "seasonal_mk", "sen"]] = list(ALL_METHODS)
    mk_variant: Literal["auto", "ess_ar1", "original", "hamed_rao", "yue_wang", "tfpw"] = "auto"
    include_series: bool = True
    include_court: bool = True

    def method_name(self) -> str:
        if self.deseasonalize is True:
            return "stl"
        if self.deseasonalize is False:
            return "none"
        return self.deseasonalize


class InsightsRequest(BaseModel):
    series_id: str
    which: list[str] = list(ALL_INSIGHTS)
    alpha: float = Field(0.05, gt=0, lt=0.5)
    forecast_horizon: int = Field(60, ge=1, le=120)
    triangle_min_years: int = Field(10, ge=3, le=50)
    min_segment_years: float = Field(4.0, ge=2.0, le=20.0)

    @field_validator("which")
    @classmethod
    def known(cls, v):
        bad = [w for w in v if w not in ALL_INSIGHTS]
        if bad:
            raise ValueError(f"unknown insights {bad}; choose from {list(ALL_INSIGHTS)}")
        return v


class CompareRequest(BaseModel):
    series_ids: list[str] = Field(..., min_length=2, max_length=20)
    alpha: float = Field(0.05, gt=0, lt=0.5)
    mode: Literal["regions", "product_agreement"] = "regions"


class NullsRequest(BaseModel):
    series_id: str
    n_null: int = Field(1000, ge=100, le=5000)
    n_panels: int = Field(19, ge=1, le=39)
    block: int = Field(12, ge=1, le=60)
    seed: int = 2026


class ScanRequest(BaseModel):
    geometry: dict
    start: str
    end: str
    variable_ids: list[str] | None = Field(None, max_length=12,
                                           description="default: recommended variables for region_type, else a core set")
    region_type: str | None = None
    alpha: float = Field(0.05, gt=0, lt=0.5)


class DriversRequest(BaseModel):
    target_series_id: str
    driver_series_ids: list[str] = Field(..., min_length=1, max_length=8)
    max_lag: int = Field(6, ge=0, le=24)
    alpha: float = Field(0.05, gt=0, lt=0.5)
    method: Literal["correlation", "pcmci"] = "correlation"
    suspects: list[dict] | None = Field(None, description="pre-registered hypotheses to stamp (pcmci only); "
                                        "driver_id must equal the driver series' variable_id")


class TrendMapRequest(BaseModel):
    variable_id: str
    geometry: dict
    start: str
    end: str
    alpha: float = Field(0.05, gt=0, lt=0.5)


class InvestigateRequest(BaseModel):
    question: str | None = Field(None, max_length=2000,
                                 examples=["Is rainfall changing in Tamil Nadu since 2001?"])
    variable_id: str | None = None
    geometry: dict | None = None
    start: str | None = None
    end: str | None = None
    insights: list[str] = list(ALL_INSIGHTS)
    explain: bool = True
    max_regions: int = Field(3, ge=1, le=5)


class TextRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class ExplainRequest(BaseModel):
    series_id: str
    include_insights: bool = True
