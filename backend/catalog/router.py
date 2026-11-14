"""Source router: variable + geometry -> ordered list of connector attempts (architecture §3 table)."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.geometry import Region
from .catalog import Catalog


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
    else:
        notes.append(f"Unknown source {src!r}")
    return routes, notes
