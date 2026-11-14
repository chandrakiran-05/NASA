"""Source router: variable + geometry -> ordered list of connector attempts (architecture §3 table)."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.geometry import Region
from .catalog import Catalog


DIRECT = {  # single-route sources (no fallback service exists for them)
    "usgs_nwis": "USGS NWIS daily values (CUAHSI WaterML)",
    "swot_hydrocron": "PO.DAAC SWOT Hydrocron",
    "erddap": "NOAA ERDDAP griddap",
    "nsidc_seaice": "NSIDC Sea Ice Index (G02135)",
    "noaa_coops": "NOAA CO-OPS tide gauge",
}


@dataclass
class Route:
    connector: str
    reason: str


def plan_routes(v: dict, region: Region, catalog: Catalog) -> tuple[list[Route], list[str]]:
    src = v.get("source")
    notes: list[str] = []
    routes: list[Route] = []
    if src == "giovanni":
        has_fallback = bool((v.get("fallback") or {}).get("concept_id"))
        if catalog.in_outage(v, point=region.is_point) and has_fallback:
            notes.append(f"Giovanni is in a reported outage for {v.get('giovanni_id')}; using the fallback.")
        else:
            # an outage with no fallback still tries Giovanni: skipping it would leave no route at all
            if catalog.in_outage(v, point=region.is_point):
                notes.append(f"Giovanni outage reported for {v.get('giovanni_id')} and no fallback exists; trying it.")
            routes.append(Route("giovanni_point", "Giovanni /timeseries (point)") if region.is_point
                          else Route("harmony_area", "Giovanni Harmony average=area"))
        if has_fallback:
            routes.append(Route("opendap", f"Cloud OPeNDAP monthly fallback ({v['fallback']['short_name']})"))
    elif src == "appeears":
        routes.append(Route("appeears", "AppEEARS point task" if region.is_point else "AppEEARS area task"))
    elif src == "ncei":
        routes.append(Route("ncei", "NCEI Access Data Service (CDO v2 fallback)"))
    elif src in DIRECT:
        routes.append(Route(src, DIRECT[src]))
    else:
        notes.append(f"Unknown source {src!r}")
    return routes, notes
