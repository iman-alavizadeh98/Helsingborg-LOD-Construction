# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Export driver — write a reconstructed tile in the formats a customer needs.

    python main.py export --tile 6204_105
    python main.py export --tile 6204_105 --format gltf ply

Reads roofer's CityJSON sequence from ``out/roofer/<tile>/`` and writes, into
``out/export/<tile>/``:

* ``<tile>.city.json`` — CityJSON 2.0, the same model as one standard file
* ``<tile>.city.gml``  — CityGML 2.0 (or 3.0), via citygml-tools
* ``<tile>.glb``       — binary glTF 2.0, one node per building, for viewers
* ``<tile>.ply``       — one binary PLY mesh, for analysis tools

Which formats are written comes from ``export.formats`` in ``config.yml``, or from
``--format``, which overrides it. roofer's own ``.city.jsonl`` is left untouched:
it is the source every export is derived from.

Every export is a conversion of that one reconstruction. Nothing is re-fitted,
simplified or smoothed, so all four formats describe identical geometry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pipeline_common.config import Config, load_config
from pipeline_common.qa_record import TileQA

from .citygml import convert_to_citygml
from .cityjson_sequence import merge_sequence, read_sequence, write_cityjson
from .gltf_writer import write_glb
from .ply_writer import write_ply
from .triangulate import mesh_sequence

FORMATS = ("cityjson", "citygml", "gltf", "ply")

# Used when config.yml has no export.mesh.colours. Linear RGB in 0..1.
DEFAULT_COLOURS = {
    "RoofSurface": [0.70, 0.27, 0.20],
    "WallSurface": [0.86, 0.84, 0.80],
    "GroundSurface": [0.35, 0.35, 0.35],
    "Other": [0.60, 0.60, 0.65],
}


def _export_section(cfg: Config) -> dict[str, Any]:
    section = cfg.get("export")
    return section if isinstance(section, dict) else {}


def _source_sequence(cfg: Config, tile_id: str) -> Path:
    """roofer's output for the tile — exactly one ``.city.jsonl`` is expected."""
    roofer_dir = cfg.out_dir / "roofer" / tile_id
    found = sorted(roofer_dir.glob("*.city.jsonl"))
    if not found:
        raise FileNotFoundError(
            f"no roofer output in {roofer_dir} — run 'python main.py roofer --tile {tile_id}' first"
        )
    if len(found) > 1:
        # roofer writes one file per tile with split-cjseq = false. Several files
        # have separate headers and transforms and cannot be merged by index offset.
        raise ValueError(
            f"{roofer_dir} holds {len(found)} .city.jsonl files; expected one. "
            f"Re-run 'python main.py roofer --tile {tile_id}' to clear stale output."
        )
    return found[0]


def export_tile(cfg: Config, tile_id: str, formats: list[str] | None = None) -> dict[str, Any]:
    ecfg = _export_section(cfg)
    formats = list(formats or ecfg.get("formats") or FORMATS)
    unknown = sorted(set(formats) - set(FORMATS))
    if unknown:
        raise ValueError(f"unknown export format(s) {unknown}; choose from {list(FORMATS)}")

    lod = str(ecfg.get("lod", "2.2"))
    colours = {**DEFAULT_COLOURS, **(ecfg.get("mesh", {}) or {}).get("colours", {})}
    out_dir = cfg.out_dir / "export" / tile_id
    out_dir.mkdir(parents=True, exist_ok=True)

    source = _source_sequence(cfg, tile_id)
    qa = TileQA(tile_id, cfg.qa_dir, config={"export": ecfg})
    rec = qa.stage("3-export")
    written: dict[str, Path] = {}

    seq = read_sequence(source)
    rec.count_in(source=source.name, buildings=len(seq.features))
    rec.metric(formats=formats, lod=lod)

    # -- CityJSON -------------------------------------------------------------
    # Also written when only CityGML is asked for: citygml-tools reads it.
    if "cityjson" in formats or "citygml" in formats:
        path = out_dir / f"{tile_id}.city.json"
        stats = write_cityjson(merge_sequence(seq), path)
        rec.count_out(cityjson_city_objects=stats["city_objects"])
        if stats["nonfinite_values_dropped"]:
            rec.metric(cityjson_nonfinite_values_dropped=stats["nonfinite_values_dropped"])
        written["cityjson"] = path
        rec.output(path)

    # -- CityGML --------------------------------------------------------------
    if "citygml" in formats:
        result = convert_to_citygml(
            cfg, written["cityjson"], out_dir, ecfg.get("citygml", {}) or {},
            log_path=cfg.qa_dir / f"{tile_id}_citygml.log",
        )
        rec.metric(citygml_version=result["citygml_version"],
                   citygml_command=" ".join(result["command"]))
        if result["exit_code"] != 0 or result["output"] is None:
            rec.failure("citygml_conversion_failed", exit_code=result["exit_code"],
                        log=str(result["log"]))
        else:
            written["citygml"] = result["output"]
            rec.output(result["output"])

    # -- meshes ---------------------------------------------------------------
    if "gltf" in formats or "ply" in formats:
        mesh = mesh_sequence(seq, lod)
        rec.count_out(meshed_buildings=len(mesh.buildings), triangles=mesh.triangle_count)
        for skipped in mesh.skipped:
            rec.failure(skipped["reason"], building=skipped["building"])
        if mesh.degenerate_faces:
            rec.metric(degenerate_faces_skipped=mesh.degenerate_faces)

        if mesh.buildings:
            if "gltf" in formats:
                path = out_dir / f"{tile_id}.glb"
                stats = write_glb(mesh, path, tile_id=tile_id, colours=colours)
                rec.metric(gltf_origin_epsg3008=stats["origin_epsg3008"])
                written["gltf"] = path
                rec.output(path)
            if "ply" in formats:
                path = out_dir / f"{tile_id}.ply"
                write_ply(mesh, path, tile_id=tile_id, colours=colours)
                written["ply"] = path
                rec.output(path)
        else:
            rec.failure("no_mesh_geometry", lod=lod)

    missing = [f for f in formats if f not in written]
    rec.count_out(formats_written=len(written), formats_failed=len(missing))
    rec.finish()
    json_path, md_path = qa.write()
    return {
        "tile": tile_id, "written": written, "failed": missing,
        "qa_md": md_path, "qa_json": json_path,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export reconstructed tiles to other formats.")
    ap.add_argument("--tile", help="tile id from config.yml; default: all tiles")
    ap.add_argument("--config", default=None, help="path to config.yml")
    ap.add_argument("--format", nargs="+", choices=FORMATS, dest="formats",
                    help="formats to write; default: export.formats in config.yml")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    tile_ids = [args.tile] if args.tile else [t.id for t in cfg.tiles()]
    if not tile_ids:
        print("no tiles configured", file=sys.stderr)
        return 2

    status = 0
    for tile_id in tile_ids:
        result = export_tile(cfg, tile_id, args.formats)
        print(f"\n=== tile {tile_id} ===")
        for fmt, path in result["written"].items():
            print(f"  {fmt:9s}: {path}")
        for fmt in result["failed"]:
            print(f"  {fmt:9s}: FAILED — see {result['qa_md']}")
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
