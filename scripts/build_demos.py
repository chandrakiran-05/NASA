#!/usr/bin/env python3
"""Fetch and cache the REAL data for every guided demo (backend/catalog/data/demos.json),
then pre-compute analyses and insights so demos load instantly on stage.

    python scripts/build_demos.py            # needs .env credentials; AppEEARS demo takes ~15 min
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.api.pipeline import cached_analysis, cached_insights  # noqa: E402
from backend.catalog.catalog import DATA  # noqa: E402
from backend.core.config import get_settings  # noqa: E402
from backend.core.geometry import parse_geometry  # noqa: E402
from backend.main import build_state  # noqa: E402
from backend.timeseries.service import parse_date  # noqa: E402


async def progress(f, m):
    print(f"   {f * 100:5.1f}%  {m}", flush=True)


async def main() -> None:
    st = build_state(get_settings())
    demos = json.loads((DATA / "demos.json").read_text())["demos"]
    for d in demos:
        print(f"== {d['id']}: {d['title']}")
        for r in d.get("compare") or [d["request"]]:
            try:
                info = await st.ts.build_series(r["variable_id"], parse_geometry(r["geometry"]), parse_date(r["start"]),
                                                parse_date(r["end"], end=True), progress=progress)
                await cached_analysis(st, info["series_id"])
                await cached_insights(st, info["series_id"])
                print(f"   OK  {info['series_id']}  {info.get('completeness')}")
            except Exception as exc:  # noqa: BLE001
                print(f"   FAILED: {getattr(exc, 'message', exc)}")
    await st.http.aclose()
    await st.llm.aclose()


if __name__ == "__main__":
    asyncio.run(main())
