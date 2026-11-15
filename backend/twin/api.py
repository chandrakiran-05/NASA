"""Digital twin mode: /api/twin/*. Separate from the verified analysis: uploads are stored as-is and
never pass through the review/verification pipeline; simulations are labelled as simulations."""
from __future__ import annotations

import io
import json
import re
import uuid

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..core.errors import InvalidRequest, NotFound
from ..timeseries.model import MonthlySeries, Provenance, utc_now_iso
from . import scenarios
from .engine import backtest, baseline, simulate, simulate_compare

router = APIRouter(prefix="/api/twin", tags=["digital twin"], default_response_class=ORJSONResponse)
TWIN_ID = re.compile(r"^t_[0-9a-f]{12}$")            # ids become file names: no path tricks


class TwinCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)


class TwinVariable(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    time: list[str]
    value: list[float | None]
    units: str | None = None


class TwinData(BaseModel):
    variables: list[TwinVariable] = Field(..., min_length=1, max_length=50)
    source: str | None = Field(None, max_length=200, description="who supplied it, e.g. 'chatbot team'")


class Shock(BaseModel):
    year: int
    size: float


class Driver(BaseModel):
    from_: str = Field(..., alias="from")
    coefficient: float


class Threshold(BaseModel):
    value: float
    direction: str = Field("above", pattern="^(above|below)$")


class Knobs(BaseModel):
    trend_multiplier: float = 1.0
    trend_add_per_decade: float = 0.0
    shocks: list[Shock] = []
    drivers: list[Driver] = []
    threshold: Threshold | None = None
    fit_since_year: int | str | None = Field(None, description='fit the trend from this year, or "auto" (last PELT break)')


class SimulateRequest(BaseModel):
    horizon_years: int = Field(30, ge=1, le=100)
    n_runs: int = Field(500, ge=50, le=2000)
    seed: int = 2026
    scenario: dict[str, Knobs] = {}
    compare_to_baseline: bool = False


def _st(request: Request):
    return request.app.state.etd


def _path(st, twin_id: str):
    if not TWIN_ID.match(twin_id):
        raise NotFound(f"Twin {twin_id!r} not found")
    return st.settings.data_dir / "twins" / f"{twin_id}.json"


def _load(st, twin_id: str) -> dict:
    p = _path(st, twin_id)
    if not p.exists():
        raise NotFound(f"Twin {twin_id!r} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _save(st, twin: dict) -> None:
    p = _path(st, twin["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(twin, indent=1), encoding="utf-8")


def _series(st, v: dict) -> MonthlySeries:
    if "time" not in v:                                    # twins saved before data moved into the twin file
        return st.store.load(v["series_id"])
    return MonthlySeries.from_arrays(v["time"], [np.nan if x is None else x for x in v["value"]], units=v.get("units"),
                                     provenance=Provenance(source_api="twin_upload", variable=v["name"], geometry={}),
                                     label=v["name"])


def _add(st, twin: dict, variables: list[TwinVariable], source: str | None) -> dict:
    for v in variables:
        if len(v.time) != len(v.value):
            raise InvalidRequest(f"{v.name}: time and value have different lengths")
        try:
            ms = MonthlySeries.from_arrays(v.time, [np.nan if x is None else x for x in v.value], units=v.units,
                                           provenance=Provenance(source_api="twin_upload", variable=v.name,
                                                                 geometry={}, notes=[f"source: {source or 'user'}"]),
                                           label=v.name)
        except ValueError as exc:
            raise InvalidRequest(f"{v.name}: could not read the dates ({exc})") from exc
        twin["variables"] = [x for x in twin["variables"] if x["name"] != v.name]   # re-upload replaces
        twin["variables"].append({"name": v.name, "units": v.units, "source": source, "uploaded_at": utc_now_iso(),
                                  # kept in the twin file: twin data must never reach the verified series store
                                  "time": [d.strftime("%Y-%m") for d in ms.time],
                                  "value": [None if not np.isfinite(x) else float(x) for x in ms.value]})
    _save(st, twin)
    return twin


@router.post("")
async def create_twin(request: Request, body: TwinCreate):
    twin = {"id": f"t_{uuid.uuid4().hex[:12]}", "name": body.name, "description": body.description,
            "created_at": utc_now_iso(), "variables": []}
    _save(_st(request), twin)
    return twin


@router.get("")
async def list_twins(request: Request):
    d = _st(request).settings.data_dir / "twins"
    twins = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("t_*.json"))] if d.exists() else []
    for t in twins:                                        # list view: names only, not the data arrays
        t["variables"] = [{k: x for k, x in v.items() if k not in ("time", "value")} for v in t["variables"]]
    return {"twins": twins}


@router.get("/{twin_id}")
async def get_twin(request: Request, twin_id: str):
    st = _st(request)
    twin = _load(st, twin_id)
    for v in twin["variables"]:
        try:
            v["baseline"] = {k: x for k, x in baseline(_series(st, v)).items() if not k.startswith("_")}
        except InvalidRequest as exc:
            v["baseline"] = {"error": exc.message}
    return twin


@router.post("/{twin_id}/data")
async def add_data(request: Request, twin_id: str, body: TwinData):
    """Research data in, as-is (JSON; for other teams' tools). Variables are kept in upload order."""
    st = _st(request)
    return _add(st, _load(st, twin_id), body.variables, body.source)


@router.post("/{twin_id}/data-csv")
async def add_csv(request: Request, twin_id: str, file: UploadFile = File(...), source: str | None = Form(None)):
    """CSV with a date column first, then one numeric column per variable."""
    st = _st(request)
    twin = _load(st, twin_id)
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise InvalidRequest("CSV larger than 20 MB")
    try:
        df = pd.read_csv(io.StringIO(raw.decode("utf-8", errors="replace")))
    except ValueError as exc:
        raise InvalidRequest(f"Could not read the CSV: {exc}") from exc
    cols = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]
    if not cols:
        raise InvalidRequest("No numeric value column found")
    t = df[df.columns[0]].astype(str).tolist()
    vs = [TwinVariable(name=str(c), time=t, value=[None if pd.isna(x) else float(x) for x in df[c]]) for c in cols]
    return _add(st, twin, vs, source or file.filename)


@router.post("/{twin_id}/simulate")
async def run_simulation(request: Request, twin_id: str, body: SimulateRequest):
    st = _st(request)
    twin = _load(st, twin_id)
    if not twin["variables"]:
        raise InvalidRequest("Upload data to this twin first")
    series = {v["name"]: _series(st, v) for v in twin["variables"]}
    scenario = {k: v.model_dump(by_alias=True, exclude_none=True) for k, v in body.scenario.items()}
    res = await run_in_threadpool(simulate_compare if body.compare_to_baseline else simulate, series, scenario, horizon_years=body.horizon_years,
                                  n_runs=body.n_runs, seed=body.seed)
    return {"twin_id": twin_id, **res}


class ImportRequest(BaseModel):
    series_id: str
    name: str | None = Field(None, max_length=80)


@router.post("/{twin_id}/import")
async def import_series(request: Request, twin_id: str, body: ImportRequest):
    """Copy a series from the main mode into the twin (one-way snapshot; the original is untouched)."""
    st = _st(request)
    twin = _load(st, twin_id)
    ms = st.store.load(body.series_id)
    v = TwinVariable(name=body.name or ms.variable_id or ms.label or body.series_id, units=ms.units,
                     time=[d.strftime("%Y-%m") for d in ms.time],
                     value=[None if not np.isfinite(x) else float(x) for x in ms.value])
    return _add(st, twin, [v], f"copy of {body.series_id} ({ms.provenance.source_api})")


class BacktestRequest(BaseModel):
    holdout_years: int = Field(10, ge=2, le=40)
    n_runs: int = Field(300, ge=50, le=2000)
    seed: int = 2026


@router.post("/{twin_id}/backtest")
async def run_backtest(request: Request, twin_id: str, body: BacktestRequest):
    """How trustworthy are this twin's bands? Hide the last years, simulate them, compare with reality."""
    st = _st(request)
    twin = _load(st, twin_id)
    if not twin["variables"]:
        raise InvalidRequest("Upload data to this twin first")
    series = {v["name"]: _series(st, v) for v in twin["variables"]}
    res = await run_in_threadpool(backtest, series, holdout_years=body.holdout_years, n_runs=body.n_runs,
                                  seed=body.seed)
    return {"twin_id": twin_id, **res}


def _twin_series(st, twin_id: str) -> dict:
    twin = _load(st, twin_id)
    if not twin["variables"]:
        raise InvalidRequest("Upload data to this twin first")
    return {v["name"]: _series(st, v) for v in twin["variables"]}


def _knobs(sc: dict[str, Knobs]) -> dict:
    return {k: v.model_dump(by_alias=True, exclude_unset=True) for k, v in sc.items()}  # unset = not a knob


class Condition(Threshold):
    variable: str


class CompoundRequest(BaseModel):
    conditions: list[Condition] = Field(..., min_length=1, max_length=5)
    horizon_years: int = Field(30, ge=1, le=100)
    n_runs: int = Field(500, ge=50, le=2000)
    seed: int = 2026
    scenario: dict[str, Knobs] = {}


@router.post("/{twin_id}/compound")
async def run_compound(request: Request, twin_id: str, body: CompoundRequest):
    """Share of simulated runs in which all conditions are met in the same year."""
    series = _twin_series(_st(request), twin_id)
    res = await run_in_threadpool(scenarios.compound, series, _knobs(body.scenario),
                                  [c.model_dump() for c in body.conditions], horizon_years=body.horizon_years,
                                  n_runs=body.n_runs, seed=body.seed)
    return {"twin_id": twin_id, **res}


class ScenarioSetRequest(BaseModel):
    scenarios: dict[str, dict[str, Knobs]] = Field(..., min_length=1, max_length=6)
    horizon_years: int = Field(30, ge=1, le=100)
    n_runs: int = Field(500, ge=50, le=2000)
    seed: int = 2026


@router.post("/{twin_id}/scenarios")
async def run_scenarios(request: Request, twin_id: str, body: ScenarioSetRequest):
    """Named scenarios side by side, one shared seed: differences come only from the knobs."""
    series = _twin_series(_st(request), twin_id)
    res = await run_in_threadpool(scenarios.scenario_set, series, {k: _knobs(v) for k, v in body.scenarios.items()},
                                  horizon_years=body.horizon_years, n_runs=body.n_runs, seed=body.seed)
    return {"twin_id": twin_id, **res}


class SensitivityRequest(BaseModel):
    target: str
    scenario: dict[str, Knobs]
    horizon_years: int = Field(30, ge=1, le=100)
    n_runs: int = Field(300, ge=50, le=2000)
    seed: int = 2026


@router.post("/{twin_id}/sensitivity")
async def run_sensitivity(request: Request, twin_id: str, body: SensitivityRequest):
    """Which knob moves the target's crossing probability most (one removed at a time, same seed)."""
    series = _twin_series(_st(request), twin_id)
    res = await run_in_threadpool(scenarios.sensitivity, series, _knobs(body.scenario), body.target,
                                  horizon_years=body.horizon_years, n_runs=body.n_runs, seed=body.seed)
    return {"twin_id": twin_id, **res}


@router.delete("/{twin_id}")
async def delete_twin(request: Request, twin_id: str):
    st = _st(request)
    _load(st, twin_id)                                     # 404 if missing
    _path(st, twin_id).unlink()
    return {"deleted": twin_id}


@router.delete("/{twin_id}/variables/{name}")
async def delete_variable(request: Request, twin_id: str, name: str):
    st = _st(request)
    twin = _load(st, twin_id)
    if not any(v["name"] == name for v in twin["variables"]):
        raise NotFound(f"Variable {name!r} not in twin {twin_id!r}")
    twin["variables"] = [v for v in twin["variables"] if v["name"] != name]
    _save(st, twin)
    return {"deleted": name, "twin_id": twin_id, "variables": [v["name"] for v in twin["variables"]]}
