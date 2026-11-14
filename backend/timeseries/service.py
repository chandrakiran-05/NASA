"""Fetch -> QC -> unit conversion -> monthly -> store. One call per (variable, region, period)."""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

from ..catalog.catalog import Catalog
from ..catalog.router import plan_routes
from ..connectors.appeears import AppEEARS
from ..connectors.base import FetchRequest, ProgressFn, _noop
from ..connectors.giovanni import GiovanniPoint
from ..connectors.harmony_area import HarmonyArea
from ..connectors.ncei import NCEIStations
from ..connectors.opendap import OpendapMonthly
from ..connectors.coops import NOAACoops
from ..core.http import BYPASS_CACHE
from ..connectors.erddap import ERDDAPGrid
from ..connectors.nsidc_seaice import NSIDCSeaIce
from ..connectors.swot import SwotHydrocron
from ..connectors.usgs_nwis import USGSNwis
from ..core.config import Settings
from ..core.errors import (CredentialsMissing, InsufficientData, InvalidRequest, TrendDetectiveError,
                           UpstreamError, UpstreamUnavailable)
from ..core.geometry import Region
from ..core.http import ResilientHTTP
from ..storage.series_store import SeriesStore, hash_request, make_series_id
from .model import MonthlySeries
from .qc import apply_qc, convert_units
from .resample import to_monthly

_UNIT_SYNONYMS = {"kgm-2s-1": "kgm-2s-1", "kg/m2/s": "kgm-2s-1", "kg/m^2/s": "kgm-2s-1", "mmhr-1": "mm/hr",
                  "mm/h": "mm/hr", "mmh-1": "mm/hr", "kelvin": "k", "degk": "k", "kgkg-1": "kg/kg",
                  "kg/kg": "kg/kg", "1": "1", "mm/day": "mm/day", "mmday-1": "mm/day", "mmd-1": "mm/day"}


def norm_units(u: str | None) -> str | None:
    if not u:
        return None
    s = re.sub(r"[\s\*\^]", "", u.strip().lower())
    return _UNIT_SYNONYMS.get(s, s)


def parse_date(s: str | date, end: bool = False) -> date:
    if isinstance(s, date):
        return s
    s = str(s)
    if re.fullmatch(r"\d{4}", s):
        return date(int(s), 12, 31) if end else date(int(s), 1, 1)
    if re.fullmatch(r"\d{4}-\d{2}", s):
        y, m = map(int, s.split("-"))
        if end:
            import calendar
            return date(y, m, calendar.monthrange(y, m)[1])
        return date(y, m, 1)
    return date.fromisoformat(s[:10])


class TimeSeriesService:
    def __init__(self, settings: Settings, http: ResilientHTTP, catalog: Catalog, store: SeriesStore):
        self.s = settings
        self.http = http
        self.catalog = catalog
        self.store = store
        self.connectors = {
            "giovanni_point": GiovanniPoint(settings, http),
            "harmony_area": HarmonyArea(settings, http),
            "opendap": OpendapMonthly(settings, http),
            "appeears": AppEEARS(settings, http),
            "ncei": NCEIStations(settings, http),
            "usgs_nwis": USGSNwis(settings, http),
            "swot_hydrocron": SwotHydrocron(settings, http),
            "erddap": ERDDAPGrid(settings, http),
            "nsidc_seaice": NSIDCSeaIce(settings, http),
            "noaa_coops": NOAACoops(settings, http),
        }

    def validate(self, variable_id: str, region: Region, start: date, end: date) -> dict:
        v = self.catalog.get(variable_id)
        if end <= start:
            raise InvalidRequest("end must be after start")
        if (end.year - start.year) * 12 + (end.month - start.month) + 1 < 24:
            raise InvalidRequest("Choose at least 2 years (10+ years recommended for trend testing)")
        cs = v.get("coverage_start")
        if cs and parse_date(cs, end=True) > end:
            raise InvalidRequest(f"{v['name']} starts in {cs}; the requested period ends before that")
        if region.is_point and "point" not in v.get("spatial_modes", ["point"]):
            raise InvalidRequest(f"{v['name']} is only available for areas")
        if not region.is_point and "area" not in v.get("spatial_modes", ["area"]):
            raise InvalidRequest(f"{v['name']} is only available for points")
        if not region.is_point and region.area_deg2 > 400 and v.get("source") == "appeears":
            raise InvalidRequest("AppEEARS area requests above ~400 square degrees are too large; draw a smaller box")
        return v

    def request_hash(self, v: dict, region: Region, start: date, end: date, options: dict) -> str:
        opts = {k: options[k] for k in sorted(options) if k in ("stations", "max_stations", "min_valid_fraction",
                                                                     "site_id", "station_id", "feature_id")}
        return hash_request(v["id"], region.key(), start.isoformat(), end.isoformat(), opts)

    async def build_series(self, variable_id: str, region: Region, start: date, end: date, *,
                           options: dict | None = None, progress: ProgressFn = _noop,
                           refresh: bool = False) -> dict:
        options = options or {}
        v = self.validate(variable_id, region, start, end)
        rh = self.request_hash(v, region, start, end, options)
        sid = make_series_id(rh)
        if not refresh and self.store.exists(sid):
            await progress(1.0, "Served from cache")
            rec = self.store.db.get_series(sid) or {}
            return {"series_id": sid, "cached": True, "completeness": rec.get("completeness"),
                    "source_api": rec.get("source_api")}

        if refresh:
            BYPASS_CACHE.set(True)       # contextvar: scoped to this job's task
        cs = v.get("coverage_start")
        eff_start = max(start, parse_date(cs)) if cs else start
        routes, notes = plan_routes(v, region, self.catalog)
        attempts = []
        raw = None
        used = None

        async def sub_progress(frac: float, msg: str):
            await progress(0.05 + 0.8 * frac, msg)

        for rt in routes:
            conn = self.connectors[rt.connector]
            try:
                await progress(0.05, f"Fetching via {rt.reason}")
                raw = await conn.fetch(FetchRequest(v, region, eff_start, end, options), sub_progress)
                used = rt
                attempts.append({"route": rt.connector, "status": "ok"})
                break
            except (UpstreamUnavailable, UpstreamError, CredentialsMissing) as exc:
                attempts.append({"route": rt.connector, "status": "failed", "code": exc.code, "error": exc.message})
                if isinstance(exc, CredentialsMissing) and rt is routes[-1]:
                    raise
                continue
        if raw is None:
            last = attempts[-1] if attempts else {}
            raise UpstreamUnavailable(
                f"Could not retrieve {v['name']}: " + (last.get("error") or "no route available"),
                detail={"attempts": attempts, "notes": notes})

        await progress(0.88, "Quality control and monthly aggregation")
        raw, qc_report = apply_qc(raw)
        conv = v.get("convert")
        fb = v.get("fallback") or {}
        if used and used.connector == "opendap" and fb.get("convert_factor"):
            raw = convert_units(raw, fb["convert_factor"], 0.0, v.get("units"))
            notes.append(f"fallback collection converted by x{fb['convert_factor']} to {v.get('units')}")
        if conv:
            src_u, seed_u = norm_units(raw.meta.units), norm_units(v.get("units"))
            if src_u is None or seed_u is None or src_u == seed_u or (used and used.connector == "opendap"
                                                                       and fb.get("convert_factor")):
                raw = convert_units(raw, conv.get("factor", 1.0), conv.get("offset", 0.0), conv["units"])
                notes.append(f"converted {v.get('units')} -> {conv['units']}")
            else:
                notes.append(f"unit conversion skipped: source reports '{raw.meta.units}', "
                             f"catalog expects '{v.get('units')}'")
        if raw.meta.units is None:
            raw = replace(raw, meta=replace(raw.meta, units=(conv or {}).get("units") or v.get("units")))
        label = region.name and f"{v['name']} — {region.name}" or v["name"]
        ms: MonthlySeries = to_monthly(raw, start=eff_start, end=end,
                                       min_valid_fraction=float(options.get("min_valid_fraction",
                                                                           self.s.min_valid_fraction_per_month)),
                                       variable_id=v["id"], label=label)
        ms.provenance.notes.extend(notes + [f"route attempts: {attempts}", f"qc: {qc_report}"])
        if ms.n_valid == 0:
            raise InsufficientData("The source returned no valid values after quality control",
                                   detail={"qc": qc_report, "attempts": attempts})
        self.store.save(ms, series_id=sid, request_hash=rh, region=region.as_dict())
        await progress(1.0, "Series ready")
        return {"series_id": sid, "cached": False, "completeness": ms.completeness(),
                "source_api": ms.provenance.source_api, "qc": qc_report, "attempts": attempts, "notes": notes}

    def save_user_series(self, ms: MonthlySeries, label: str | None = None) -> str:
        import hashlib
        import json as _json
        payload = _json.dumps({"t": [str(t) for t in ms.time], "v": [None if v != v else v for v in ms.value.tolist()],
                               "u": ms.units, "l": label}, sort_keys=True)
        rh = hashlib.sha256(payload.encode()).hexdigest()
        sid = "u_" + rh[:16]
        ms.label = label or ms.label or "Uploaded series"
        self.store.save(ms, series_id=sid, request_hash=rh, region=ms.provenance.geometry or None)
        return sid


def classify_error(exc: Exception) -> dict:
    if isinstance(exc, TrendDetectiveError):
        return {"code": exc.code, "message": exc.message, "detail": exc.detail}
    return {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}
