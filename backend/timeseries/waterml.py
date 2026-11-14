"""CUAHSI-compatible exports of a monthly series: OGC WaterML 2.0 XML and a HydroShare-friendly CSV.

CUAHSI HIS and HydroShare consume WaterML; missing months are written as explicit nil / "missing"
points, never filled.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from .model import MonthlySeries, utc_now_iso

NS = {"wml2": "http://www.opengis.net/waterml/2.0", "gml": "http://www.opengis.net/gml/3.2",
      "om": "http://www.opengis.net/om/2.0", "xlink": "http://www.w3.org/1999/xlink",
      "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
for _p, _u in NS.items():
    ET.register_namespace(_p, _u)
NIL_MISSING = "http://www.opengis.net/def/nil/OGC/0/missing"
AVERAGE_SUCC = "http://www.opengis.net/def/waterml/2.0/interpolationType/AverageSucc"


def _q(tag: str) -> str:
    p, name = tag.split(":")
    return f"{{{NS[p]}}}{name}"


def _el(parent, tag: str, text: str | None = None, **attrs) -> ET.Element:
    e = ET.SubElement(parent, _q(tag), {(_q(k.replace("__", ":")) if "__" in k else k): v for k, v in attrs.items()})
    if text is not None:
        e.text = text
    return e


def _meta(ms: MonthlySeries, series_id: str, variable: dict | None) -> dict:
    v, p = variable or {}, ms.provenance
    doi = p.doi or (v.get("dataset") or {}).get("doi")
    return {"series_id": series_id, "site": (p.geometry or {}).get("name") or str(p.geometry or ""),
            "site_or_product_id": p.product_id or "",
            "variable": f"{v.get('name') or ms.label or p.variable} ({v.get('id') or ms.variable_id or p.variable})",
            "units": ms.units or "", "source": " ".join(x for x in (p.source_api, p.dataset_short_name, p.version) if x),
            "doi_or_url": f"https://doi.org/{doi}" if doi else (p.request_url or ""),
            "retrieved_at": p.retrieved_at, "aggregation": "monthly mean; missing months are left missing"}


def _iso(ts) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_waterml2(ms: MonthlySeries, *, series_id: str, variable: dict | None) -> str:
    m = _meta(ms, series_id, variable)
    gid = re.sub(r"[^A-Za-z0-9_.-]", "_", series_id)
    root = ET.Element(_q("wml2:Collection"), {_q("gml:id"): f"C.{gid}"})
    _el(root, "gml:description", "\n".join(f"{k}: {v}" for k, v in m.items())
        + "".join(f"\nnote: {n}" for n in ms.provenance.notes))
    doc = _el(_el(root, "wml2:metadata"), "wml2:DocumentMetadata", gml__id=f"D.{gid}")
    _el(doc, "wml2:generationDate", utc_now_iso())
    _el(doc, "wml2:generationSystem", "Earth System Trend Detective")
    obs = _el(_el(root, "wml2:observationMember"), "om:OM_Observation", gml__id=f"O.{gid}")
    period = _el(_el(obs, "om:phenomenonTime"), "gml:TimePeriod", gml__id=f"P.{gid}")
    _el(period, "gml:beginPosition", _iso(ms.time[0]) if ms.n else None)
    _el(period, "gml:endPosition", _iso(ms.time[-1]) if ms.n else None)
    _el(_el(_el(obs, "om:resultTime"), "gml:TimeInstant", gml__id=f"R.{gid}"), "gml:timePosition",
        m["retrieved_at"])
    _el(obs, "om:procedure", xlink__href=m["doi_or_url"] or "urn:unknown", xlink__title=m["source"])
    _el(obs, "om:observedProperty", xlink__href=f"urn:etd:variable:{(variable or {}).get('id') or ms.variable_id}",
        xlink__title=m["variable"])
    _el(obs, "om:featureOfInterest", xlink__href=f"urn:etd:series:{gid}", xlink__title=m["site"])
    ts = _el(_el(obs, "om:result"), "wml2:MeasurementTimeseries", gml__id=f"T.{gid}")
    _el(_el(_el(ts, "wml2:metadata"), "wml2:MeasurementTimeseriesMetadata"), "wml2:temporalExtent",
        xlink__href=f"#P.{gid}")
    dm = _el(_el(ts, "wml2:defaultPointMetadata"), "wml2:DefaultTVPMeasurementMetadata")
    _el(dm, "wml2:uom", code=m["units"])
    _el(dm, "wml2:interpolationType", xlink__href=AVERAGE_SUCC, xlink__title="Average in succeeding interval")
    _el(dm, "wml2:aggregationDuration", "P1M")
    for t, val in zip(ms.time, ms.value):
        tvp = _el(_el(ts, "wml2:point"), "wml2:MeasurementTVP")
        _el(tvp, "wml2:time", _iso(t))
        if math.isfinite(val):
            _el(tvp, "wml2:value", repr(float(val)))
        else:
            _el(tvp, "wml2:value", xsi__nil="true")
            _el(_el(_el(tvp, "wml2:metadata"), "wml2:TVPMeasurementMetadata"), "wml2:nilReason",
                xlink__href=NIL_MISSING)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def to_cuahsi_csv(ms: MonthlySeries, *, series_id: str, variable: dict | None) -> str:
    m = _meta(ms, series_id, variable)
    head = [f"# {k}: {v}" for k, v in m.items()] + [f"# note: {n}".replace("\n", " ") for n in ms.provenance.notes]
    rows = [f"{t.strftime('%Y-%m-%dT%H:%M:%S')},{repr(float(v))}," if math.isfinite(v)
            else f"{t.strftime('%Y-%m-%dT%H:%M:%S')},,missing" for t, v in zip(ms.time, ms.value)]
    return "\n".join(head + ["DateTime,Value,Qualifier"] + rows) + "\n"
