"""Inspect roofer's CityJSON output — Phase 2 acceptance evidence.

    python -m pipeline.inspect_cityjson --tile 6204_105

Reports what actually came out: how many buildings, which LoDs, whether the
semantic surfaces LOD2.2 requires (RoofSurface / WallSurface / GroundSurface)
are present and separated, and the roof-form mix roofer assigned.

Reads CityJSON (``.city.json``) and CityJSONSequence (``.city.jsonl``, one
metadata line followed by one CityJSONFeature per line) without cjio, which is
not installed.

Volumes are computed on recentred coordinates: at y~6.2e6 the divergence-theorem
sum loses all its precision otherwise, which is the bug that once produced
5x10^8 m3 for a house.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from .config import load_config


def _vertices(doc: dict, transform: dict | None) -> np.ndarray:
    """Vertices in real-world coordinates, applying the CityJSON transform.

    In a CityJSONSequence the ``transform`` appears **only** on the leading
    metadata line; every following CityJSONFeature carries raw integer vertices
    that must be scaled and translated with that same transform. Applying a
    feature's own (absent) transform leaves the vertices 1/scale too large —
    1000x here — which turns a 5 m house into a 5000 m one.
    """
    verts = np.asarray(doc.get("vertices", []), dtype=np.float64)
    if verts.size == 0:
        return verts.reshape(0, 3)
    tr = doc.get("transform") or transform
    if tr:
        verts = verts * np.asarray(tr["scale"], dtype=np.float64)
        verts = verts + np.asarray(tr["translate"], dtype=np.float64)
    return verts


def _iter_documents(path: Path):
    """Yield (city_objects, vertices) pairs from CityJSON or CityJSONSequence."""
    if path.suffix == ".jsonl" or path.name.endswith(".city.jsonl"):
        transform = None
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                doc = json.loads(line)
                # The first line is the metadata header: no objects, but it
                # carries the transform every later feature depends on.
                if doc.get("type") == "CityJSON" and not doc.get("CityObjects"):
                    transform = doc.get("transform") or transform
                    continue
                yield doc.get("CityObjects", {}), _vertices(doc, transform)
    else:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        yield doc.get("CityObjects", {}), _vertices(doc, None)


def _shell_volume(shell: list, verts: np.ndarray) -> float:
    """Signed volume of a closed shell by the divergence theorem."""
    idx = [i for face in shell for ring in face[:1] for i in ring]
    if not idx:
        return 0.0
    origin = verts[list(dict.fromkeys(idx))].mean(axis=0)

    total = 0.0
    for face in shell:
        if not face:
            continue
        ring = face[0]
        if len(ring) < 3:
            continue
        pts = verts[ring] - origin
        a = pts[0]
        for i in range(1, len(pts) - 1):
            total += float(np.dot(a, np.cross(pts[i], pts[i + 1])))
    return abs(total) / 6.0


def inspect(path: Path) -> dict:
    objects = 0
    lods: Counter = Counter()
    surfaces: Counter = Counter()
    roof_types: Counter = Counter()
    parents = 0
    volumes: list[float] = []
    heights: list[float] = []
    no_geometry = 0

    for city_objects, verts in _iter_documents(path):
        for _, obj in city_objects.items():
            otype = obj.get("type", "")
            if otype == "Building":
                parents += 1
            if otype not in ("Building", "BuildingPart"):
                continue
            objects += 1

            attrs = obj.get("attributes", {}) or {}
            for key in ("rf_roof_type", "roof_type", "roofType"):
                if key in attrs and attrs[key] is not None:
                    roof_types[str(attrs[key])] += 1
                    break

            geoms = obj.get("geometry", []) or []
            if not geoms:
                no_geometry += 1
                continue

            for geom in geoms:
                lod = str(geom.get("lod", "?"))
                lods[lod] += 1
                sem = geom.get("semantics", {}) or {}
                for s in sem.get("surfaces", []) or []:
                    surfaces[s.get("type", "unknown")] += 1

                if lod == "2.2" and geom.get("type") == "Solid" and verts.size:
                    boundaries = geom.get("boundaries", [])
                    if boundaries:
                        volumes.append(_shell_volume(boundaries[0], verts))
                        idx = [i for face in boundaries[0] for ring in face[:1] for i in ring]
                        if idx:
                            z = verts[list(set(idx)), 2]
                            heights.append(float(z.max() - z.min()))

    def stats(values: list[float]) -> dict | None:
        if not values:
            return None
        arr = np.asarray(values)
        return {
            "n": int(arr.size),
            "min": round(float(arr.min()), 2),
            "median": round(float(np.median(arr)), 2),
            "max": round(float(arr.max()), 2),
        }

    return {
        "file": str(path),
        "buildings": parents,
        "building_objects": objects,
        "objects_without_geometry": no_geometry,
        "lods": dict(lods),
        "semantic_surfaces": dict(surfaces),
        "roof_types": dict(roof_types),
        "lod22_volume_m3": stats(volumes),
        "lod22_height_m": stats(heights),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inspect roofer CityJSON output.")
    ap.add_argument("--tile", help="tile id from config.yml")
    ap.add_argument("--config", default=None)
    ap.add_argument("--path", help="inspect this file instead of the tile output")
    args = ap.parse_args(argv)

    if args.path:
        files = [Path(args.path)]
    else:
        cfg = load_config(args.config)
        tile_ids = [args.tile] if args.tile else [t.id for t in cfg.tiles()]
        files = []
        for tile_id in tile_ids:
            out_dir = cfg.out_dir / "roofer" / tile_id
            files += sorted(
                p for p in out_dir.rglob("*")
                if p.suffix in (".json", ".jsonl") or ".city." in p.name
            )

    if not files:
        print("no CityJSON output found — run 'python -m pipeline.run_roofer' first")
        return 1

    for path in files:
        print(json.dumps(inspect(path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
