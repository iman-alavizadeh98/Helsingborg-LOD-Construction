# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Phase 2 driver — reconstruct one prepared tile with roofer.

    python -m pipeline.run_roofer --tile 6204_105

Consumes the Phase 1 outputs (``<tile>_prepared.las`` and
``<tile>_roofprints.gpkg``), writes a roofer TOML, runs roofer, and records the
result in the tile's QA report.

roofer is run as a separate process and only its CityJSON is consumed, so its
GPL-3.0 licence imposes no obligation on this code (PROJECT_PLAN §2).

**Why the prepared LAS matters.** ``src/extra/io/StreamCropper.cpp`` keeps a
point only when its classification equals ``building_class`` or
``ground_class``; every other class is dropped on the floor. Feeding roofer the
raw tile would silently discard all 861k class-12 returns. Phase 1 therefore
relabels recovered roof points to class 6 before roofer ever sees them.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, load_config
from .qa_record import TileQA


def _toml_path(root: Path, path: Path, container_root: str | None) -> str:
    """Render a path for the TOML, rebased into the container when needed."""
    if container_root is None:
        return str(path).replace("\\", "/")
    rel = path.resolve().relative_to(root.resolve())
    return f"{container_root.rstrip('/')}/{rel.as_posix()}"


def build_toml(cfg: Config, tile_id: str, container_root: str | None) -> str:
    """Render the roofer configuration for one tile."""
    rcfg = cfg.section("roofer")
    rec = rcfg.get("reconstruction", {}) or {}
    root = cfg.root
    work = cfg.work_dir / tile_id
    out_dir = cfg.out_dir / "roofer" / tile_id
    out_dir.mkdir(parents=True, exist_ok=True)

    gpkg = _toml_path(root, work / f"{tile_id}_roofprints.gpkg", container_root)
    las = _toml_path(root, work / f"{tile_id}_prepared.las", container_root)
    out = _toml_path(root, out_dir, container_root)

    lines = [
        f'polygon-source = "{gpkg}"',
        'polygon-source-layer = "roofprints"',
        f'id-attribute = "{rcfg.get("id_attribute", "bid")}"',
        f'srs = "{cfg.crs}"',
        f'output-directory = "{out}"',
        "split-cjseq = false",
        f'bld-class = {int(rcfg.get("bld_class", 6))}',
        f'grnd-class = {int(rcfg.get("grnd_class", 2))}',
    ]

    # LoD selection is per-level booleans; there is no `lod = 22` key.
    for level in ("lod12", "lod13", "lod22"):
        lines.append(f"{level} = {str(bool(rcfg.get(level, level == 'lod22'))).lower()}")

    for key, toml_key in (
        ("ceil_point_density", "ceil-point-density"),
        ("cellsize", "cellsize"),
        ("plane_detect_epsilon", "plane-detect-epsilon"),
        ("plane_detect_k", "plane-detect-k"),
        ("plane_detect_min_points", "plane-detect-min-points"),
        ("complexity_factor", "complexity-factor"),
        ("lod13_step_height", "lod13-step-height"),
    ):
        if key in rec and rec[key] is not None:
            lines.append(f"{toml_key} = {rec[key]}")

    lines += [
        "",
        "[[pointclouds]]",
        f'name = "{tile_id}"',
        f'source = ["{las}"]',
        f'building_class = {int(rcfg.get("bld_class", 6))}',
        f'ground_class = {int(rcfg.get("grnd_class", 2))}',
        "",
    ]
    return "\n".join(lines)


def run_roofer(cfg: Config, tile_id: str, dry_run: bool = False) -> dict:
    rcfg = cfg.section("roofer")
    runner = str(rcfg.get("runner", "docker"))
    work = cfg.work_dir / tile_id
    out_dir = cfg.out_dir / "roofer" / tile_id

    for required in (work / f"{tile_id}_prepared.las",
                     work / f"{tile_id}_roofprints.gpkg"):
        if not required.is_file():
            raise FileNotFoundError(
                f"{required} is missing — run 'python -m pipeline.prepare_tile "
                f"--tile {tile_id}' first"
            )

    # Clear previous output first: roofer names files after the tile origin, so
    # a run with different inputs leaves the old files in place beside the new
    # ones and the directory silently mixes two results.
    if out_dir.exists():
        shutil.rmtree(out_dir)

    container_root = rcfg.get("container_root", "/work") if runner == "docker" else None
    toml_text = build_toml(cfg, tile_id, container_root)
    toml_path = work / f"{tile_id}_roofer.toml"
    toml_path.write_text(toml_text, encoding="utf-8")

    if runner == "docker":
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{cfg.root}:{container_root}",
            str(rcfg.get("image", "roofer:1.0.0")),
            "--config", _toml_path(cfg.root, toml_path, container_root),
        ]
    else:
        binary = str(rcfg.get("binary", "roofer"))
        if shutil.which(binary) is None:
            raise FileNotFoundError(f"roofer binary '{binary}' not found on PATH")
        cmd = [binary, "--config", str(toml_path)]

    qa = TileQA(tile_id, cfg.qa_dir, config={"roofer": rcfg})
    rec = qa.stage("2-roofer")
    rec.count_in(config=str(toml_path), runner=runner)

    if dry_run:
        rec.metric(command=" ".join(cmd), dry_run=True).finish()
        qa.write()
        return {"tile": tile_id, "command": cmd, "toml": toml_path, "dry_run": True}

    proc = subprocess.run(cmd, capture_output=True, text=True)
    log_path = cfg.qa_dir / f"{tile_id}_roofer.log"
    log_path.write_text(
        f"$ {' '.join(cmd)}\n\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
        encoding="utf-8",
    )

    produced = sorted(p for p in out_dir.rglob("*") if p.is_file())
    rec.count_out(
        exit_code=proc.returncode,
        files_written=len(produced),
        bytes_written=sum(p.stat().st_size for p in produced),
    )
    rec.metric(command=" ".join(cmd))
    for p in produced[:50]:
        rec.output(p)
    if proc.returncode != 0:
        rec.failure("roofer_nonzero_exit", exit_code=proc.returncode,
                    log=str(log_path))
    elif not produced:
        rec.failure("roofer_no_output", log=str(log_path))
    rec.finish()

    json_path, md_path = qa.write()
    return {
        "tile": tile_id, "command": cmd, "toml": toml_path,
        "exit_code": proc.returncode, "outputs": produced,
        "log": log_path, "qa_md": md_path, "qa_json": json_path,
        "stdout": proc.stdout, "stderr": proc.stderr,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconstruct a tile with roofer (Phase 2).")
    ap.add_argument("--tile", help="tile id from config.yml; default: all tiles")
    ap.add_argument("--config", default=None, help="path to config.yml")
    ap.add_argument("--dry-run", action="store_true",
                    help="write the roofer TOML and print the command, run nothing")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    tile_ids = [args.tile] if args.tile else [t.id for t in cfg.tiles()]
    if not tile_ids:
        print("no tiles configured", file=sys.stderr)
        return 2

    status = 0
    for tile_id in tile_ids:
        result = run_roofer(cfg, tile_id, dry_run=args.dry_run)
        print(f"\n=== tile {tile_id} ===")
        print(f"  config : {result['toml']}")
        print(f"  command: {' '.join(result['command'])}")
        if result.get("dry_run"):
            continue
        print(f"  exit   : {result['exit_code']}")
        print(f"  outputs: {len(result['outputs'])} file(s)")
        for p in result["outputs"][:10]:
            print(f"    - {p}")
        if result["exit_code"] != 0:
            print(f"  log    : {result['log']}")
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
