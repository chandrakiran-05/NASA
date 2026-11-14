"""CMR Search API — collection/variable metadata and granule listings.

Paging: page_size <= 2000 with the CMR-Search-After header. Throttling: 429 + retry-after,
handled by ResilientHTTP.
"""
from __future__ import annotations

from datetime import date

from ..core.http import ResilientHTTP


class CMR:
    def __init__(self, base: str, http: ResilientHTTP):
        self.base = base.rstrip("/")
        self.http = http

    async def collection(self, *, short_name: str | None = None, concept_id: str | None = None,
                         version: str | None = None) -> dict | None:
        params = {"page_size": 10}
        if concept_id:
            params["concept_id"] = concept_id
        if short_name:
            params["short_name"] = short_name
        if version:
            params["version"] = version
        r = await self.http.request("GET", f"{self.base}/collections.json", params=params)
        entries = r.json().get("feed", {}).get("entry", [])
        return entries[0] if entries else None

    async def variables(self, keyword: str, page_size: int = 50) -> list[dict]:
        r = await self.http.request("GET", f"{self.base}/variables.json",
                                    params={"keyword": keyword, "page_size": page_size})
        return r.json().get("items", [])

    async def granules(self, concept_id: str, start: date, end: date, bbox: tuple | None = None,
                       page_size: int = 2000, max_pages: int = 50) -> list[dict]:
        params = {"concept_id": concept_id, "page_size": page_size, "sort_key": "start_date",
                  "temporal": f"{start.isoformat()}T00:00:00Z,{end.isoformat()}T23:59:59Z"}
        if bbox:
            params["bounding_box"] = ",".join(str(x) for x in bbox)
        out: list[dict] = []
        search_after = None
        for _ in range(max_pages):
            headers = {"CMR-Search-After": search_after} if search_after else None
            r = await self.http.request("GET", f"{self.base}/granules.json", params=params, headers=headers)
            entries = r.json().get("feed", {}).get("entry", [])
            out.extend(entries)
            search_after = r.headers.get("cmr-search-after")
            if not search_after or len(entries) < page_size:
                break
        return out
