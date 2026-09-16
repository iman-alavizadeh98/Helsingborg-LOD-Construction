# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Single entry point for the whole LOD2.2 pipeline.

Reached three ways, all equivalent — ``python main.py`` from a clone, ``python -m
pipeline.cli`` once ``src/`` is importable, or the ``helsingborg-lod22`` command
after ``pip install -e .``. The examples below use the first.

    python main.py all --tile 6204_105      # the usual command

Every stage is also runnable on its own, in the order below:

    python main.py footprints               # cadastral footprints, Swedish -> English
    python main.py prepare  --tile 6204_105 # Phase 1: DTM, point recovery, roofprints
    python main.py roofer   --tile 6204_105 # Phase 2: reconstruct with roofer
    python main.py inspect  --tile 6204_105 # report LoDs, roof forms, volumes

``--tile`` is optional everywhere: omit it and every tile in ``config.yml`` is
processed. ``--config`` points at a different ``config.yml``; paths inside it
resolve against its own directory, so these commands work from any directory.

``footprints`` sits apart from the other three. It regenerates the cadastral
input from Lantmäteriet's national Byggnad GeoPackage, which is not shipped with
this repository — you only need it when refreshing the footprints, not on a
normal run. That is why ``all`` does not include it.

Exit codes: ``0`` success, ``1`` a stage failed, ``2`` a configuration problem.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Stage entry points. Each is a `main(argv) -> int` following the same
# convention, so this module dispatches rather than reimplementing anything.
from . import inspect_cityjson, prepare_tile, run_roofer

# The order `all` runs them in, and the labels used in its progress output.
PHASES = (
    ("prepare", "Phase 1 — prepare tile", prepare_tile.main),
    ("roofer", "Phase 2 — reconstruct with roofer", run_roofer.main),
    ("inspect", "Phase 3 — inspect output", inspect_cityjson.main),
)


def _forward(args: argparse.Namespace, *, dry_run: bool = False) -> list[str]:
    """Rebuild the argv a stage's own parser expects."""
    argv: list[str] = []
    if getattr(args, "tile", None):
        argv += ["--tile", args.tile]
    if getattr(args, "config", None):
        argv += ["--config", args.config]
    if dry_run and getattr(args, "dry_run", False):
        argv.append("--dry-run")
    return argv


def run_footprints(args: argparse.Namespace) -> int:
    """Regenerate the cadastral footprint layer from the raw Byggnad extract."""
    # Imported here rather than at module scope: this stage is the only one that
    # needs the buildings package, and a normal run should not pay for it.
    from .buildings import BuildingsPipeline

    # Check the input up front. BasePipeline.run() catches everything and logs a
    # traceback, which is the right behaviour mid-run but poor for a mistyped
    # path — by far the most likely way this stage is invoked wrongly.
    if not Path(args.input).is_file():
        print(f"input GeoPackage not found: {args.input}", file=sys.stderr)
        return 2

    cfg = {
        "input_gpkg": args.input,
        "input_layer": args.layer,
        "postprocess": not args.no_postprocess,
    }
    result = BuildingsPipeline(config=cfg).run(output_dir=args.output)

    if result.get("status") != "success":
        print(f"footprints failed: {result.get('error')}", file=sys.stderr)
        return 1

    print(f"\nfootprints written to {args.output}")
    post = result.get("validation_report", {})
    if post.get("issues"):
        print("  validation issues:")
        for issue in post["issues"]:
            print(f"    - {issue}")
    return 0


def run_all(args: argparse.Namespace) -> int:
    """Run prepare -> roofer -> inspect, stopping at the first failure.

    Stopping matters: a failed prepare leaves no prepared LAS, and roofer would
    then fail again with a less informative message about a missing input.
    """
    for name, label, entry in PHASES:
        print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
        status = entry(_forward(args, dry_run=(name == "roofer")))
        if status != 0:
            print(
                f"\n{label} failed (exit {status}); stopping before the "
                f"remaining stages.",
                file=sys.stderr,
            )
            return status
    print(f"\n{'=' * 70}\nAll stages complete.\n{'=' * 70}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="LOD2.2 building reconstruction for Helsingborg.",
        epilog="Run '<command> --help' for a command's options.",
    )
    sub = ap.add_subparsers(dest="command", required=True, metavar="<command>")

    def add_tile_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--tile", help="tile id from config.yml; default: all tiles")
        parser.add_argument("--config", default=None, help="path to config.yml")

    p_all = sub.add_parser("all", help="prepare, reconstruct and inspect one tile")
    add_tile_args(p_all)
    p_all.add_argument("--dry-run", action="store_true",
                       help="for the roofer stage: write the TOML and print the command only")

    p_prepare = sub.add_parser("prepare", help="Phase 1: DTM, point recovery, roofprints")
    add_tile_args(p_prepare)

    p_roofer = sub.add_parser("roofer", help="Phase 2: reconstruct with roofer")
    add_tile_args(p_roofer)
    p_roofer.add_argument("--dry-run", action="store_true",
                          help="write the roofer TOML and print the command, run nothing")

    p_inspect = sub.add_parser("inspect", help="report LoDs, roof forms, volumes")
    add_tile_args(p_inspect)
    p_inspect.add_argument("--path", help="inspect this file instead of the tile output")

    p_fp = sub.add_parser(
        "footprints",
        help="regenerate cadastral footprints from the raw Byggnad GeoPackage",
    )
    p_fp.add_argument("--input", required=True,
                      help="path to the raw Lantmäteriet Byggnad GeoPackage")
    p_fp.add_argument("--layer", default=None,
                      help="layer within the input; default: the first layer")
    p_fp.add_argument("--output", default="data",
                      help="output directory (default: data)")
    p_fp.add_argument("--no-postprocess", action="store_true",
                      help="skip the newest-row-per-building snapshot")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "all":
        return run_all(args)
    if args.command == "footprints":
        return run_footprints(args)
    if args.command == "prepare":
        return prepare_tile.main(_forward(args))
    if args.command == "roofer":
        return run_roofer.main(_forward(args, dry_run=True))
    if args.command == "inspect":
        argv_inspect = _forward(args)
        if args.path:
            argv_inspect += ["--path", args.path]
        return inspect_cityjson.main(argv_inspect)

    # argparse's required=True makes this unreachable; kept so a future
    # subcommand added to the parser but not here fails loudly.
    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
