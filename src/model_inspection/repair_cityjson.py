# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Repair CityJSON / CityJSONSeq files that browsers refuse to parse.

The main offender is the bare ``NaN`` token: Python's ``json`` module emits it
happily, but it is not JSON, so ``JSON.parse`` in ninja.cityjson.org (and any
other strict parser) aborts on the whole file.

Usage::

    python -m model_inspection.repair_cityjson out/roofer/6204_105/*.city.jsonl
    python -m model_inspection.repair_cityjson out/roofer/6204_105/*.city.jsonl --set-lod 2.2

(with ``src/`` on ``PYTHONPATH``, or after ``pip install -e .``)

Writes ``<name>.fixed.city.json`` next to the input unless ``-o`` is given.

This is a viewer aid, not a pipeline stage — roofer's own output parses fine.
Reach for it when a file has been through a tool that emitted bare ``NaN``, or
when a viewer insists on a particular LoD label.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

NONFINITE = "nonfinite"


def _clean(node, stats, drop_key=None):
    """Recursively replace non-finite floats. Dict entries are dropped."""
    if isinstance(node, float) and not math.isfinite(node):
        stats[NONFINITE] += 1
        return None
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            cleaned = _clean(v, stats)
            if cleaned is None and isinstance(v, float):
                continue  # drop the attribute rather than emit null
            out[k] = cleaned
        return out
    if isinstance(node, list):
        return [_clean(v, stats) for v in node]
    return node


def _set_lod(obj, lod, stats):
    for co in obj.get("CityObjects", {}).values():
        for geom in co.get("geometry", []):
            if str(geom.get("lod")) != lod:
                geom["lod"] = lod
                stats["lod"] += 1


def fix_document(doc, lod, stats):
    doc = _clean(doc, stats)
    if lod:
        _set_lod(doc, lod, stats)
    return doc


def fix_file(path: Path, out: Path, lod: str | None) -> dict:
    stats = {NONFINITE: 0, "lod": 0, "lines": 0}
    text = path.read_text(encoding="utf-8")
    seq = path.suffixes[-1:] == [".jsonl"]

    if seq:
        parts = []
        for line in text.splitlines():
            if not line.strip():
                continue
            stats["lines"] += 1
            doc = fix_document(json.loads(line), lod, stats)
            parts.append(json.dumps(doc, allow_nan=False, separators=(",", ":")))
        out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    else:
        doc = fix_document(json.loads(text), lod, stats)
        out.write_text(
            json.dumps(doc, allow_nan=False, separators=(",", ":")), encoding="utf-8"
        )
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="output path (single input only)")
    ap.add_argument("--set-lod", metavar="LOD", help='rewrite every geometry lod, e.g. "2.2"')
    args = ap.parse_args()

    if args.output and len(args.inputs) > 1:
        ap.error("-o takes a single input")

    for src in args.inputs:
        if args.output:
            dst = args.output
        else:
            name = src.name.replace(".city.", ".fixed.city.", 1)
            dst = src.with_name(name if name != src.name else src.stem + ".fixed" + src.suffix)
        stats = fix_file(src, dst, args.set_lod)
        print(
            f"{src.name} -> {dst.name}: "
            f"{stats[NONFINITE]} non-finite dropped, {stats['lod']} lod rewritten"
            + (f", {stats['lines']} features" if stats["lines"] else "")
        )


if __name__ == "__main__":
    main()
