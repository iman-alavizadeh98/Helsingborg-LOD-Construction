# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Render a tile's QA record as one self-contained HTML page.

Written next to ``<tile>_qa.md`` from the same data. It adds what plain text does
badly:

* a stage overview with runtime bars, so the slow stage is obvious at a glance
* a **flagged-buildings** table that gathers every issue for a building across all
  stages — building 104 is flagged by diagnosis *and* by export, for one cause
* each failure kind explained in plain words
* nested values (the buffer sweep) as real tables, not a comma-joined line
* output files as links, relative to the report so the folder can be moved

The page is fully self-contained — no scripts, fonts or stylesheets fetched from
anywhere — so it opens offline and survives being emailed. It follows the
viewer's light or dark preference and prints cleanly.
"""

from __future__ import annotations

import html
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .qa_record import _fmt, _fmt_field

# Plain-language titles for the stages the pipeline writes. Unknown stages fall
# back to their raw name, so a new stage never breaks the report.
STAGE_TITLES = {
    "0-load": "Load point cloud",
    "1.5-tiling": "Tile extent",
    "1.1-dtm": "Ground model (DTM)",
    "1.2-recover": "Roof point recovery",
    "1.3-footprints": "Cadastral footprints",
    "1.3-offset": "Footprint → roofprint offset",
    "1.4-diagnose": "Footprint diagnosis",
    "1.3-buffer-sweep": "Roofprint buffer sweep",
    "1-outputs": "Prepared inputs for roofer",
    "2-roofer": "Reconstruction (roofer)",
    "3-export": "Export (CityJSON, CityGML, glTF, PLY)",
}

# What each failure kind means, for a reader who has not read the code.
FAILURE_HELP = {
    "no_returns": "No LiDAR returns of any class inside the footprint — a gap in the scan.",
    "below_height_threshold": "Returns exist, but none reach the minimum height above "
                              "ground. Usually a low shed or garage.",
    "absent_building": "Returns are mostly ground: the cadastral record is probably "
                       "out of date and the building is gone.",
    "no_roof_points": "Tall returns exist, but none survived vegetation filtering.",
    "footprint_without_points": "No recovered roof points fall inside the footprint.",
    "dtm_nodata_cells": "Terrain cells too far from any ground return to be filled.",
    "roofer_nonzero_exit": "roofer exited with an error — see its log.",
    "roofer_no_output": "roofer ran but wrote no files — see its log.",
    "citygml_conversion_failed": "citygml-tools failed to write CityGML — see its log.",
    "no_mesh_geometry": "No building in the tile had geometry at the export LoD.",
}

# Failure detail keys that identify a building.
_BUILDING_KEYS = ("bid", "building", "building_id")


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _key(name: str) -> str:
    """A field name that wraps at underscores, never mid-word."""
    return _e(name).replace("_", "_<wbr>")


def _is_records(value: Any) -> bool:
    """A list of row dicts — rendered as its own full-width table."""
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def _failure_help(kind: str) -> str:
    if kind in FAILURE_HELP:
        return FAILURE_HELP[kind]
    match = re.fullmatch(r"no_lod(\d)(\d)_geometry", kind)
    if match:
        lod = f"{match.group(1)}.{match.group(2)}"
        return (f"roofer produced no LoD {lod} solid for this building, so it is "
                f"missing from the glTF and PLY exports.")
    return ""


def _stage_id(name: str) -> str:
    return "stage-" + re.sub(r"[^A-Za-z0-9_-]+", "-", name)


def _link(path_str: str, qa_dir: Path) -> str:
    """A link to a file, relative to the report where possible."""
    path = Path(path_str)
    try:
        href = Path(os.path.relpath(path, qa_dir)).as_posix()
    except ValueError:
        # Different drive from the report on Windows: no relative path exists.
        href = path.as_uri() if path.is_absolute() else path.as_posix()
    return f'<a href="{_e(href)}">{_e(path.name)}</a> <span class="muted path">{_e(path.parent)}</span>'


def _value(key: str, value: Any, qa_dir: Path) -> str:
    """Render one value; nested structures become nested tables."""
    if _is_records(value):
        return _records_table(value, qa_dir)
    if isinstance(value, dict) and value:
        return _kv_table(value, qa_dir, css="nested")
    if key in ("log",) and isinstance(value, str):
        return _link(value, qa_dir)
    text = _fmt_field(key, value)
    css = "num" if isinstance(value, (int, float)) and not isinstance(value, bool) else ""
    return f'<span class="{css}">{_e(text)}</span>' if css else _e(text)


def _kv_table(block: dict[str, Any], qa_dir: Path, css: str = "kv") -> str:
    rows = "".join(
        f"<tr><th scope='row'>{_key(k)}</th><td>{_value(k, v, qa_dir)}</td></tr>"
        for k, v in block.items()
    )
    return f'<table class="{css}"><tbody>{rows}</tbody></table>'


def _records_table(records: list[dict[str, Any]], qa_dir: Path) -> str:
    keys: list[str] = []
    for rec in records:
        for k in rec:
            if k not in keys:
                keys.append(k)
    head = "".join(f"<th scope='col'>{_key(k)}</th>" for k in keys)
    body = "".join(
        "<tr>" + "".join(f"<td>{_value(k, rec.get(k), qa_dir)}</td>" for k in keys) + "</tr>"
        for rec in records
    )
    return f'<div class="scroll"><table class="grid"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _flagged_buildings(stages: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """Building id → [(stage, failure kind), ...], across every stage."""
    found: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for stage in stages:
        for failure in stage["failures"]:
            for key in _BUILDING_KEYS:
                if failure.get(key) is not None:
                    found[str(failure[key])].append((stage["stage"], failure["kind"]))
                    break
    return dict(sorted(found.items(), key=lambda kv: (len(kv[0]), kv[0])))


def _when(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def render_html(data: dict[str, Any], qa_dir: Path) -> str:
    """The complete HTML document for one tile's QA record."""
    qa_dir = Path(qa_dir)
    tile = data.get("tile_id", "")
    stages = data.get("stages", [])
    total_s = sum(s.get("seconds") or 0.0 for s in stages)
    slowest = max((s.get("seconds") or 0.0 for s in stages), default=0.0) or 1.0
    n_flagged = sum(len(s["failures"]) for s in stages)
    n_outputs = sum(len(s["outputs"]) for s in stages)
    flagged_buildings = _flagged_buildings(stages)
    platform = data.get("platform", {})

    parts: list[str] = []
    add = parts.append

    # -- header and summary ---------------------------------------------------
    add(f"<header><p class='eyebrow'>QA report</p><h1>Tile {_e(tile)}</h1>")
    add(f"<p class='muted'>Generated {_e(_when(data.get('finished_utc')))} · "
        f"first stage started {_e(_when(data.get('started_utc')))} · "
        f"Python {_e(platform.get('python', '?'))} on {_e(platform.get('system', '?'))}</p></header>")

    status = "ok" if n_flagged == 0 else "warn"
    add("<section class='summary' aria-label='Summary'>")
    for label, value, css in (
        ("Stages", f"{len(stages)}", ""),
        ("Runtime", f"{total_s:,.1f} s", ""),
        ("Flagged items", f"{n_flagged}", status),
        ("Buildings flagged", f"{len(flagged_buildings)}", status if flagged_buildings else "ok"),
        ("Output files", f"{n_outputs}", ""),
    ):
        add(f"<div class='stat {css}'><span class='label'>{label}</span><span class='value'>{_e(value)}</span></div>")
    add("</section>")

    # -- stage overview -------------------------------------------------------
    add("<section><h2>Stages</h2><div class='scroll'><table class='grid overview'>"
        "<thead><tr><th scope='col'>Stage</th><th scope='col'>Runtime</th>"
        "<th scope='col' class='r'>Flagged</th></tr></thead><tbody>")
    for s in stages:
        secs = s.get("seconds") or 0.0
        width = max(0.5, 100.0 * secs / slowest)
        flags = len(s["failures"])
        badge = f"<span class='badge warn'>{flags}</span>" if flags else "<span class='badge ok'>0</span>"
        add(f"<tr><td><a href='#{_stage_id(s['stage'])}'>{_e(STAGE_TITLES.get(s['stage'], s['stage']))}</a>"
            f" <span class='muted code'>{_e(s['stage'])}</span></td>"
            f"<td class='bar-cell'><span class='bar' style='width:{width:.1f}%'></span>"
            f"<span class='num'>{secs:,.2f} s</span></td><td class='r'>{badge}</td></tr>")
    add("</tbody></table></div></section>")

    # -- flagged buildings ----------------------------------------------------
    if flagged_buildings:
        add("<section><h2>Flagged buildings</h2>"
            "<p class='muted'>Every issue recorded for a building, across all stages. "
            "Building ids are the footprint <code>bid</code>, the same id used in the "
            "exported models.</p><div class='scroll'><table class='grid'>"
            "<thead><tr><th scope='col'>Building</th><th scope='col'>Issues</th></tr></thead><tbody>")
        for bid, issues in flagged_buildings.items():
            items = "".join(
                f"<li><span class='kind'>{_e(kind)}</span> "
                f"<span class='muted'>in <a href='#{_stage_id(stage)}'>{_e(stage)}</a></span></li>"
                for stage, kind in issues
            )
            add(f"<tr><td class='code'>{_e(bid)}</td><td><ul class='issues'>{items}</ul></td></tr>")
        add("</tbody></table></div></section>")

    # -- per-stage detail -----------------------------------------------------
    add("<section><h2>Stage details</h2>")
    for s in stages:
        flags = s["failures"]
        title = STAGE_TITLES.get(s["stage"], s["stage"])
        secs = s.get("seconds")
        badge = (f"<span class='badge warn'>{len(flags)} flagged</span>" if flags
                 else "<span class='badge ok'>no issues</span>")
        add(f"<details class='stage' id='{_stage_id(s['stage'])}' open>"
            f"<summary><span class='title'>{_e(title)}</span>"
            f"<span class='muted code'>{_e(s['stage'])}</span>"
            f"<span class='muted'>{'' if secs is None else f'{secs:,.2f} s'}</span>{badge}</summary>")

        # Scalar values go in the side-by-side key/value blocks. A value that is
        # itself a table (the buffer sweep) is lifted out to full width below:
        # nested in a narrow cell it crushed its key to one letter per line.
        blocks, wide = [], []
        for block_title, block in (("Counts in", s["counts_in"]), ("Counts out", s["counts_out"]),
                                   ("Metrics", s["metrics"])):
            scalars = {k: v for k, v in block.items() if not _is_records(v)}
            wide += [(block_title, k, v) for k, v in block.items() if _is_records(v)]
            if scalars:
                blocks.append((block_title, scalars))
        if blocks:
            add("<div class='blocks'>")
            for block_title, block in blocks:
                add(f"<div class='block'><h3>{block_title}</h3>{_kv_table(block, qa_dir)}</div>")
            add("</div>")
        for block_title, name, records in wide:
            add(f"<h3>{block_title} · {_key(name)}</h3>{_records_table(records, qa_dir)}")

        if flags:
            by_kind: dict[str, int] = defaultdict(int)
            for f in flags:
                by_kind[f["kind"]] += 1
            add("<h3>Flagged</h3><ul class='kinds'>")
            for kind, count in by_kind.items():
                explanation = _failure_help(kind)
                add(f"<li><span class='badge warn'>{count}</span> <span class='kind'>{_e(kind)}</span>"
                    + (f" <span class='muted'>— {_e(explanation)}</span>" if explanation else "")
                    + "</li>")
            add("</ul>")
            add(f"<details class='inner'{' open' if len(flags) <= 20 else ''}>"
                f"<summary>All {len(flags)} flagged item{'s' if len(flags) != 1 else ''}</summary>"
                f"{_records_table(flags, qa_dir)}</details>")

        if s["outputs"]:
            add("<h3>Outputs</h3><ul class='outputs'>")
            add("".join(f"<li>{_link(o, qa_dir)}</li>" for o in s["outputs"]))
            add("</ul>")
        add("</details>")
    add("</section>")

    # -- configuration --------------------------------------------------------
    add("<section><h2>Configuration</h2><details class='inner'><summary>"
        "Settings recorded with this report</summary><pre>"
        f"{_e(json.dumps(data.get('config', {}), indent=2, ensure_ascii=False))}</pre></details></section>")

    add("<footer class='muted'>Written by helsingborg-lod22 from "
        f"<code>{_e(tile)}_qa.json</code>, which holds the complete record.</footer>")

    return (
        "<!doctype html>\n<html lang='en'>\n<head>\n<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        f"<title>QA report — tile {_e(tile)}</title>\n<style>{_CSS}</style>\n</head>\n"
        f"<body><main>{''.join(parts)}</main></body>\n</html>\n"
    )


_CSS = """
:root {
  --bg: #f7f7f5; --panel: #ffffff; --text: #1d1f21; --muted: #6a6f76;
  --line: #e2e2de; --accent: #2f6fb3; --ok: #2e7d4f; --ok-bg: #e5f3ea;
  --warn: #9a5b00; --warn-bg: #fdf0dc; --bar: #9cbde0;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15171a; --panel: #1e2125; --text: #e6e6e3; --muted: #9aa0a6;
    --line: #33373d; --accent: #7fb0e6; --ok: #7ccf9a; --ok-bg: #1d3326;
    --warn: #f0b561; --warn-bg: #3a2c16; --bar: #3d6590;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 30px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 20px; margin: 36px 0 12px; }
h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted); margin: 18px 0 8px; font-weight: 600; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code, .code { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 0.9em; }
.eyebrow { text-transform: uppercase; letter-spacing: 0.08em; font-size: 12px;
  color: var(--muted); margin: 0; font-weight: 600; }
.muted { color: var(--muted); }
.path { font-size: 12px; overflow-wrap: anywhere; }
.num { font-variant-numeric: tabular-nums; }
.r { text-align: right; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px; margin-top: 24px; }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px; display: flex; flex-direction: column; }
.stat .label { font-size: 12px; color: var(--muted); }
.stat .value { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; }
.stat.warn .value { color: var(--warn); }
.stat.ok .value { color: var(--ok); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
.grid, .kv { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden; }
.grid th, .grid td, .kv th, .kv td { padding: 7px 12px; border-bottom: 1px solid var(--line);
  text-align: left; vertical-align: top; }
.grid tbody tr:last-child td, .kv tbody tr:last-child th, .kv tbody tr:last-child td { border-bottom: 0; }
.grid thead th { font-size: 12px; color: var(--muted); font-weight: 600; white-space: nowrap; }
.kv th { font-weight: 500; color: var(--muted); width: 45%; }
.kv td { overflow-wrap: anywhere; }
.nested { width: auto; }
.nested th, .nested td { padding: 2px 10px 2px 0; border: 0; font-size: 13px; }
.nested th { color: var(--muted); font-weight: 500; }
.overview td { white-space: nowrap; }
.bar-cell { position: relative; min-width: 180px; width: 45%; }
.bar { display: inline-block; height: 8px; border-radius: 4px; background: var(--bar);
  margin-right: 8px; vertical-align: middle; max-width: calc(100% - 80px); }
.badge { display: inline-block; min-width: 22px; padding: 1px 8px; border-radius: 999px;
  font-size: 12px; font-weight: 600; text-align: center; font-variant-numeric: tabular-nums; }
.badge.ok { color: var(--ok); background: var(--ok-bg); }
.badge.warn { color: var(--warn); background: var(--warn-bg); }
.kind { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 0.9em; }
ul.issues, ul.kinds, ul.outputs { margin: 0; padding-left: 0; list-style: none; }
ul.issues li, ul.kinds li, ul.outputs li { margin: 3px 0; }
details.stage { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 0 18px; margin: 12px 0; }
details.stage > summary { cursor: pointer; padding: 14px 0; display: flex; flex-wrap: wrap;
  gap: 6px 14px; align-items: baseline; list-style: none; }
details.stage > summary::-webkit-details-marker { display: none; }
details.stage > summary::before { content: "▸"; color: var(--muted); }
details.stage[open] > summary::before { content: "▾"; }
details.stage[open] { padding-bottom: 16px; }
details.stage .title { font-weight: 650; font-size: 16px; }
details.stage .kv { background: var(--bg); }
details.stage .grid { background: var(--bg); }
.blocks { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 0 18px; }
details.inner > summary { cursor: pointer; color: var(--accent); margin: 8px 0; }
pre { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px; overflow-x: auto; font-size: 12.5px; }
footer { margin-top: 40px; font-size: 13px; }
@media (max-width: 600px) {
  main { padding: 20px 16px 48px; }
  h1 { font-size: 24px; }
  .kv th { width: 50%; }
}
@media print {
  body { background: #fff; }
  details.stage { break-inside: avoid; }
  .bar { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
}
"""
