"""Printable condition / QC report generation.

Compiles the session's catalogue metadata, dimensions/scale, quality verdict,
colour conformance (CIE dE2000 / FADGI), AI condition findings (cracks,
discolouration), provenance, fixity and annotations into a single, self-
contained HTML document that a curator can print to PDF for an object's
condition record or a publication appendix.
"""

from __future__ import annotations

import html
from typing import Any


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _kv_table(rows: list[tuple[str, Any]]) -> str:
    body = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in rows if v not in (None, "", [])
    )
    return f"<table class='kv'>{body}</table>" if body else "<p class='muted'>—</p>"


def render_report(context: dict) -> str:
    session = context.get("session", {})
    meta = context.get("metadata", {}) or {}
    quality = context.get("quality") or {}
    color = context.get("color") or {}
    condition = context.get("condition") or {}
    provenance = context.get("provenance") or {}
    manifest = context.get("manifest") or {}
    annotations = context.get("annotations") or []
    ppm = session.get("pixels_per_mm")

    qmetrics = quality.get("metrics", {})
    verdict = quality.get("verdict", "—")
    cmetrics = {
        "Calibrated": color.get("calibrated"),
        "Method": color.get("method"),
        "ΔE2000 mean": color.get("delta_e_mean"),
        "ΔE2000 max": color.get("delta_e_max"),
        "Conformance": f"{color.get('conformance_target', '')} → {color.get('conformance_pass')}"
        if color else None,
    }

    def dims_mm(px):
        if ppm and px:
            return f"{px} px ({px / ppm:.1f} mm)"
        return f"{px} px" if px else None

    ann_rows = ""
    for a in annotations:
        shape = a.get("shape", "point")
        extent = ""
        if shape == "rect" and a.get("w") and ppm:
            extent = f"{a['w'] / ppm:.1f} × {a['h'] / ppm:.1f} mm"
        elif shape == "rect" and a.get("w"):
            extent = f"{a['w']:.0f} × {a['h']:.0f} px"
        ann_rows += (
            f"<tr><td>{_esc(a.get('id'))}</td><td>{_esc(shape)}</td>"
            f"<td>{_esc(a.get('text'))}</td><td>{_esc(a.get('tags'))}</td><td>{_esc(extent)}</td></tr>"
        )
    ann_table = (
        "<table class='grid'><thead><tr><th>#</th><th>Type</th><th>Note</th><th>Tags</th><th>Extent</th></tr></thead>"
        f"<tbody>{ann_rows}</tbody></table>"
        if ann_rows else "<p class='muted'>No annotations.</p>"
    )

    cracks = condition.get("cracks", [])
    disc = condition.get("discolouration", [])
    verdict_class = {"ok": "ok", "warn": "warn", "broken": "bad"}.get(verdict, "")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"/>
<title>Condition Report — {_esc(meta.get('title') or session.get('name'))}</title>
<style>
  :root {{ --ink:#1b1e25; --muted:#6c6456; --line:#ded7c7; --accent:#1c6b62; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:"Iowan Old Style","Palatino Linotype",Georgia,"Nanum Myeongjo",serif; color:var(--ink);
    max-width:880px; margin:28px auto; padding:0 22px; line-height:1.5; }}
  .sans {{ font-family:system-ui,"Segoe UI","Noto Sans KR",sans-serif; }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:14px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:flex-end; }}
  .kicker {{ font-family:system-ui,sans-serif; letter-spacing:.22em; font-size:11px; font-weight:700; color:var(--accent); }}
  h1 {{ margin:6px 0 0; font-size:26px; }}
  h2 {{ font-size:15px; font-family:system-ui,sans-serif; letter-spacing:.04em; text-transform:uppercase; color:var(--muted);
    border-bottom:1px solid var(--line); padding-bottom:5px; margin:26px 0 10px; }}
  table {{ border-collapse:collapse; width:100%; font-family:system-ui,sans-serif; font-size:13px; }}
  table.kv th {{ text-align:left; width:34%; color:var(--muted); font-weight:600; padding:5px 8px; vertical-align:top; }}
  table.kv td {{ padding:5px 8px; }}
  table.grid th, table.grid td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; }}
  table.grid th {{ background:#f3efe7; color:var(--muted); }}
  .badge {{ display:inline-block; padding:3px 12px; border-radius:999px; font-family:system-ui,sans-serif; font-weight:700; font-size:12px; }}
  .badge.ok {{ background:#dcefe4; color:#1c6b62; }} .badge.warn {{ background:#fbf0d6; color:#9a6a12; }}
  .badge.bad {{ background:#f6dcd6; color:#ad3a2c; }}
  .muted {{ color:var(--muted); }}
  footer {{ margin-top:34px; padding-top:12px; border-top:1px solid var(--line); font-family:system-ui,sans-serif; font-size:11px; color:var(--muted); }}
  @media print {{ body {{ margin:0; }} h2 {{ break-after:avoid; }} table {{ break-inside:avoid; }} }}
</style></head><body>
<header>
  <div><div class="kicker">CONDITION &amp; ACQUISITION REPORT</div>
    <h1>{_esc(meta.get('title') or session.get('name') or 'Untitled')}</h1></div>
  <div class="sans" style="text-align:right">Verdict <span class="badge {verdict_class}">{_esc(verdict).upper()}</span></div>
</header>

<h2>Object</h2>
{_kv_table([
    ("Title", meta.get("title")), ("Creator", meta.get("creator")), ("Date", meta.get("date")),
    ("Material", meta.get("material")), ("Repository", meta.get("repository")),
    ("Accession no.", meta.get("accession_number")), ("Dimensions", meta.get("dimensions")),
    ("Subject", meta.get("subject")), ("Rights", meta.get("rights")), ("Description", meta.get("description")),
])}

<h2>Acquisition</h2>
{_kv_table([
    ("Session ID", session.get("id")), ("Status", session.get("status")),
    ("Mosaic width", dims_mm(session.get("width"))), ("Mosaic height", dims_mm(session.get("height"))),
    ("Scale", f"{ppm:.3f} px/mm ({ppm * 25.4:.0f} DPI)" if ppm else None),
    ("Source images", session.get("image_count")), ("Auto tags", session.get("tags")),
])}

<h2>Image Quality (QC)</h2>
{_kv_table([
    ("Verdict", verdict), ("Issues", "; ".join(quality.get("issues", [])) or "none"),
    ("Coverage", qmetrics.get("coverage_ratio")), ("Hole count", qmetrics.get("hole_count")),
    ("Sharpness", qmetrics.get("sharpness")), ("Perceptual quality", qmetrics.get("perceptual_quality")),
    ("Registration RMS", qmetrics.get("registration_rms")),
])}

<h2>Colour Accuracy</h2>
{_kv_table(list(cmetrics.items()))}

<h2>AI Condition Analysis</h2>
{_kv_table([
    ("Cracks detected", len(cracks)), ("Discolouration regions", len(disc)),
    ("Crack density", condition.get("crack_density")), ("Discolour fraction", condition.get("discolour_fraction")),
])}

<h2>Annotations</h2>
{ann_table}

<h2>Provenance &amp; Integrity</h2>
{_kv_table([
    ("Synthetic (reconstructed) fraction", provenance.get("synthetic_fraction")),
    ("Mean uncertainty", provenance.get("mean_uncertainty")),
    ("Artefacts (fixity)", len(manifest.get("fixity", []))),
    ("Created (UTC)", manifest.get("created_utc")),
])}

<footer>Generated by Hyper Gigapixel Agent. Reconstructed/synthetic pixels are flagged in the provenance layer and are not measurements.</footer>
</body></html>"""
