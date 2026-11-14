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
        outage = catalog.in_outage(v, point=region.is_point)
        if outage:
            notes.append(f"Giovanni is in a reported outage for {v.get('giovanni_id')}; using the fallback.")
        elif region.is_point:
            routes.append(Route("giovanni_point", "Giovanni /timeseries (point)"))
        else:
            routes.append(Route("harmony_area", "Giovanni Harmony average=area"))
        if (v.get("fallback") or {}).get("concept_id"):
            routes.append(Route("opendap", f"Cloud OPeNDAP monthly fallback ({v['fallback']['short_name']})"))
        if not routes:
            notes.append("No fallback collection is configured for this variable during the outage.")
    elif src == "appeears":
        routes.append(Route("appeears", "AppEEARS point task" if region.is_point else "AppEEARS area task"))
    elif src == "ncei":
        routes.append(Route("ncei", "NCEI Access Data Service (CDO v2 fallback)"))
    elif src in DIRECT:
        routes.append(Route(src, DIRECT[src]))
    else:
        notes.append(f"Unknown source {src!r}")
    return routes, notes
