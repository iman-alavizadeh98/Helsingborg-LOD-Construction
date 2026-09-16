# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Write a tile as one binary PLY mesh.

PLY suits analysis tools — CloudCompare, MeshLab, Open3D — rather than viewers,
so this keeps what those tools can use:

* **real-world coordinates**, as ``double``. Unlike glTF, PLY is not limited to
  float32, so nothing is recentred and the file lines up with the LiDAR tile and
  the other exports without any offset. (CloudCompare will offer a "global shift"
  on import; that is its own display conditioning, and it is reversible.)
* **per-face properties**: a colour by semantic class, plus ``building`` (the
  building id) and ``semantic`` (0 ground, 1 wall, 2 roof, 3 other) as integers,
  so faces can be filtered or split by either in the receiving tool.

All buildings go into one file; the ``building`` property separates them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .triangulate import SEMANTIC_NAMES, TileMesh

_FACE_DTYPE = np.dtype([
    ("count", "u1"),
    ("vertex_indices", "<i4", (3,)),
    ("red", "u1"), ("green", "u1"), ("blue", "u1"),
    ("building", "<i4"),
    ("semantic", "u1"),
])


def _building_number(building_id: str, attributes: dict[str, Any], fallback: int) -> int:
    """An integer id for the ``building`` face property.

    roofer's feature ids are the footprint ``bid`` values, which are integers; use
    them so a face can be traced back to the footprint table. A non-numeric id
    falls back to the building's position in the file.
    """
    for candidate in (attributes.get("bid"), building_id):
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return fallback


def write_ply(
    tile: TileMesh,
    path: Path | str,
    *,
    tile_id: str,
    colours: dict[str, list[float]],
) -> dict[str, Any]:
    """Write ``tile`` to ``path`` as a binary little-endian PLY."""
    if not tile.buildings:
        raise ValueError(f"tile {tile_id} has no building geometry at LoD {tile.lod}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    palette = np.array([
        [round(255 * c) for c in colours.get(name, colours.get("Other", [0.8, 0.8, 0.8]))]
        for name in SEMANTIC_NAMES
    ], dtype=np.uint8)

    vertex_blocks, face_blocks = [], []
    offset = 0
    for number, building in enumerate(tile.buildings):
        vertex_blocks.append(building.vertices.astype("<f8"))
        faces = np.zeros(len(building.triangles), dtype=_FACE_DTYPE)
        faces["count"] = 3
        faces["vertex_indices"] = building.triangles + offset
        rgb = palette[building.semantics]
        faces["red"], faces["green"], faces["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
        faces["building"] = _building_number(building.building_id, building.attributes, number)
        faces["semantic"] = building.semantics
        face_blocks.append(faces)
        offset += len(building.vertices)

    vertices = np.vstack(vertex_blocks)
    faces = np.concatenate(face_blocks)

    header = "\n".join([
        "ply",
        "format binary_little_endian 1.0",
        f"comment tile {tile_id}, LoD {tile.lod}, written by helsingborg-lod22",
        f"comment crs {tile.crs or 'unknown'} (real-world coordinates, not recentred)",
        "comment semantic 0=GroundSurface 1=WallSurface 2=RoofSurface 3=Other",
        "comment building = roofer building id (the footprint bid)",
        f"element vertex {len(vertices)}",
        "property double x",
        "property double y",
        "property double z",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        "property int building",
        "property uchar semantic",
        "end_header",
    ]) + "\n"

    with open(path, "wb") as fh:
        fh.write(header.encode("ascii"))
        fh.write(np.ascontiguousarray(vertices).tobytes())
        fh.write(faces.tobytes())

    return {
        "buildings": len(tile.buildings),
        "vertices": int(len(vertices)),
        "triangles": int(len(faces)),
        "bytes": path.stat().st_size,
    }
