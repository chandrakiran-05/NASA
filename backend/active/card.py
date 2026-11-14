"""Printable trend card as SVG (A4-ish, no plotting dependency). Draws only numbers from the view;
gaps stay gaps (the line breaks at nulls)."""
from __future__ import annotations

import textwrap
from html import escape

W, H = 794, 1123                       # A4 at 96 dpi
PX, PY, PW, PH = 70, 150, 660, 340     # plot box


def _wrap(text: str, width: int = 95) -> list[str]:
    return textwrap.wrap(text or "", width)


def _path(xs, ys, x0, x1, y0, y1) -> str:
    out, pen = [], False
    for i, y in enumerate(ys):
        if y is None:
            pen = False
            continue
        px = PX + (xs[i] - x0) / max(x1 - x0, 1) * PW
        py = PY + PH - (y - y0) / max(y1 - y0, 1e-12) * PH
        out.append(f"{'L' if pen else 'M'}{px:.1f},{py:.1f}")
        pen = True
    return " ".join(out)


def card_svg(v: dict) -> str:
    ch = v.get("chart") or {}
    t = ch.get("time") or []
    obs = ch.get("observed") or []
    xs = list(range(len(t)))
    vals = [y for y in obs + (ch.get("sen_line") or []) if y is not None]
    y0, y1 = (min(vals), max(vals)) if vals else (0.0, 1.0)
    pad = (y1 - y0) * 0.05 or 1.0
    y0, y1 = y0 - pad, y1 + pad
    x1 = max(len(t) - 1, 1)
    verdict = (v.get("verdict") or {})
    lab = verdict.get("label") or ("SIGNIFICANT" if verdict.get("significant") else "")
    colour = {"VERIFIED": "#1a7f37", "PROBABLE": "#9a6700", "NOT VERIFIED": "#cf222e"}.get(lab, "#444")
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Segoe UI, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="{PX}" y="60" font-size="24" font-weight="700">{escape(v.get("label") or v.get("series_id", ""))}</text>',
         f'<text x="{PX}" y="90" font-size="14" fill="#555">Units: {escape(str(v.get("units") or "-"))}'
         f' &#183; {escape(t[0] if t else "")} to {escape(t[-1] if t else "")}</text>']
    if lab:
        s.append(f'<rect x="{PX}" y="102" rx="6" width="{18 + 9 * len(lab)}" height="28" fill="{colour}"/>'
                 f'<text x="{PX + 9}" y="122" font-size="15" font-weight="700" fill="#fff">{escape(lab)}</text>')
    s.append(f'<rect x="{PX}" y="{PY}" width="{PW}" height="{PH}" fill="#fafbfc" stroke="#d0d7de"/>')
    prob = ch.get("change_probability") or []
    for i, p in enumerate(prob):        # BEAST change probability as a soft band along the bottom
        if p:
            h = min(p * 8, 1.0) * 40
            s.append(f'<rect x="{PX + i / x1 * PW:.1f}" y="{PY + PH - h:.1f}" width="{PW / x1 + 0.5:.1f}" '
                     f'height="{h:.1f}" fill="#8250df" opacity="0.25"/>')
    for m in v.get("markers") or []:
        if m.get("date") in t:
            px = PX + t.index(m["date"]) / x1 * PW
            dash = "" if m["kind"].startswith("beast_confirmed") else ' stroke-dasharray="4 4"'
            col = "#8250df" if m["kind"].startswith("beast") else "#0969da"
            s.append(f'<line x1="{px:.1f}" y1="{PY}" x2="{px:.1f}" y2="{PY + PH}" stroke="{col}"{dash}/>')
    s.append(f'<path d="{_path(xs, obs, 0, x1, y0, y1)}" fill="none" stroke="#57606a" stroke-width="1"/>')
    if ch.get("sen_line"):
        s.append(f'<path d="{_path(xs, ch["sen_line"], 0, x1, y0, y1)}" fill="none" stroke="#cf222e" stroke-width="2.5"/>')
    s.append(f'<text x="{PX - 8}" y="{PY + 12}" font-size="11" text-anchor="end">{y1:.3g}</text>'
             f'<text x="{PX - 8}" y="{PY + PH}" font-size="11" text-anchor="end">{y0:.3g}</text>')
    ly = PY + PH + 28
    s.append(f'<text x="{PX}" y="{ly}" font-size="12" fill="#555">'
             f'<tspan fill="#57606a">&#9473; observed</tspan>   <tspan fill="#cf222e">&#9473; trend (Sen)</tspan>   '
             f'<tspan fill="#8250df">&#9474; BEAST change (solid = confirmed)</tspan>   '
             f'<tspan fill="#0969da">&#9474; PELT break</tspan>   <tspan fill="#8250df">&#9608; change probability</tspan></text>')
    y = ly + 40
    for title, body in (("Verdict", v.get("caption")),
                        (((v.get("explanation") or {}).get("label") or "Explanation").capitalize(),
                         (v.get("explanation") or {}).get("text")),
                        ("Limits", " ".join(v.get("limits") or []))):
        if not body:
            continue
        s.append(f'<text x="{PX}" y="{y}" font-size="15" font-weight="700">{escape(title)}</text>')
        y += 22
        for line in _wrap(body)[:12]:
            s.append(f'<text x="{PX}" y="{y}" font-size="13">{escape(line)}</text>')
            y += 18
        y += 14
    s.append(f'<text x="{PX}" y="{H - 30}" font-size="10" fill="#888">Series {escape(v.get("series_id", ""))} '
             f'&#183; numbers computed by the backend; text checked against them &#183; Earth System Trend Detective</text>')
    s.append("</svg>")
    return "\n".join(s)
