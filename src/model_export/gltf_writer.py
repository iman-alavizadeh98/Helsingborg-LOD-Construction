# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Write a tile as binary glTF 2.0 (``.glb``).

Structure of the file:

* one root node for the tile, carrying the georeference in its ``extras``
* one child node per building, named by building id, with the building's
  attributes in ``extras`` — so a viewer that shows node names and extras lets you
  identify and query a building by clicking it
* each building mesh has up to three primitives, one per semantic class, each
  with its own material: roof, wall and ground are separately selectable

**Two deliberate departures from the source coordinates, both forced by glTF.**

1. *Recentred.* glTF stores vertex positions as float32, which resolves about
   0.5 m at 6.2 × 10⁶ m — roofs would visibly snap to a coarse grid. Positions are
   written relative to a whole-metre ``origin`` near the tile centre, and that
   origin is recorded in the root node's ``extras`` (and the asset's) as
   ``georeference.origin_epsg3008``. Add it back to recover real-world coordinates
   to the millimetre. This is the only place in the project that uses a local
   frame; the CityJSON, CityGML and PLY exports keep real-world coordinates.
2. *Y-up.* glTF is Y-up; EPSG:3008 is east/north/up. The mapping is
   ``(east, north, up) → (x, y, z) = (east, up, −north)``, a proper rotation, so
   handedness and face orientation are preserved.

Normals are not written. glTF requires viewers to compute flat normals when none
are given, and flat shading is exactly right for planar LOD2 faces.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from model_inspection.repair_cityjson import fix_document

from .triangulate import SEMANTIC_NAMES, TileMesh

# glTF constants (spec §3.6 and §5).
_FLOAT = 5126
_UNSIGNED_INT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4

_GLB_MAGIC = 0x46546C67      # "glTF"
_CHUNK_JSON = 0x4E4F534A     # "JSON"
_CHUNK_BIN = 0x004E4942      # "BIN\0"


def _to_gltf_axes(local: np.ndarray) -> np.ndarray:
    """East/north/up → glTF x/y/z = east/up/−north."""
    return np.column_stack((local[:, 0], local[:, 2], -local[:, 1]))


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    """Drop non-finite numbers, which are not valid JSON and break glTF loaders."""
    return fix_document(value, None, {"nonfinite": 0, "lod": 0})


def write_glb(
    tile: TileMesh,
    path: Path | str,
    *,
    tile_id: str,
    colours: dict[str, list[float]],
) -> dict[str, Any]:
    """Write ``tile`` to ``path`` as a single self-contained ``.glb`` file."""
    if not tile.buildings:
        raise ValueError(f"tile {tile_id} has no building geometry at LoD {tile.lod}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lo, hi = tile.bounds()
    origin = np.floor((lo + hi) / 2.0)

    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    def add_view(data: bytes, target: int) -> int:
        # Every view starts on a 4-byte boundary: float32 accessors require it.
        binary.extend(b"\x00" * (-len(binary) % 4))
        buffer_views.append({
            "buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": target,
        })
        binary.extend(data)
        return len(buffer_views) - 1

    # One material per semantic class that actually occurs.
    present = sorted({int(c) for b in tile.buildings for c in np.unique(b.semantics)})
    material_index = {}
    materials = []
    for code in present:
        name = SEMANTIC_NAMES[code]
        rgb = colours.get(name, colours.get("Other", [0.8, 0.8, 0.8]))
        material_index[code] = len(materials)
        materials.append({
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            # Roofer's solids are outward-facing, but many viewers cull back faces;
            # double-sided keeps an occasional reversed face visible, not a hole.
            "doubleSided": True,
        })

    meshes: list[dict[str, Any]] = []
    building_nodes: list[dict[str, Any]] = []
    for building in tile.buildings:
        positions = _to_gltf_axes(building.vertices - origin).astype(np.float32)
        pos_view = add_view(positions.tobytes(), _ARRAY_BUFFER)
        accessors.append({
            "bufferView": pos_view, "componentType": _FLOAT, "count": len(positions),
            "type": "VEC3",
            "min": [float(v) for v in positions.min(axis=0)],
            "max": [float(v) for v in positions.max(axis=0)],
        })
        pos_accessor = len(accessors) - 1

        primitives = []
        for code in np.unique(building.semantics):
            idx = building.triangles[building.semantics == code].astype(np.uint32).ravel()
            view = add_view(idx.tobytes(), _ELEMENT_ARRAY_BUFFER)
            accessors.append({
                "bufferView": view, "componentType": _UNSIGNED_INT,
                "count": int(idx.size), "type": "SCALAR",
            })
            primitives.append({
                "attributes": {"POSITION": pos_accessor},
                "indices": len(accessors) - 1,
                "material": material_index[int(code)],
                "mode": _TRIANGLES,
            })

        meshes.append({"name": building.building_id, "primitives": primitives})
        building_nodes.append({
            "name": building.building_id,
            "mesh": len(meshes) - 1,
            "extras": {"building_id": building.building_id,
                       **_json_safe(dict(building.attributes))},
        })

    georeference = {
        "crs": tile.crs,
        "origin_epsg3008": [float(v) for v in origin],
        "axes": "x = east, y = up, z = -north; add origin after undoing the axis swap",
        "lod": tile.lod,
    }
    nodes = [{
        "name": f"tile {tile_id}",
        "children": list(range(1, len(building_nodes) + 1)),
        "extras": {"georeference": georeference},
    }] + building_nodes

    binary.extend(b"\x00" * (-len(binary) % 4))
    gltf = {
        "asset": {
            "version": "2.0",
            "generator": "helsingborg-lod22 model_export",
            "extras": {"georeference": georeference, "tile": tile_id},
        },
        "scene": 0,
        "scenes": [{"name": f"tile {tile_id}", "nodes": [0]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(binary)}],
    }

    json_chunk = json.dumps(gltf, allow_nan=False, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)   # JSON chunk pads with spaces
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)

    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", _GLB_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_chunk), _CHUNK_JSON))
        fh.write(json_chunk)
        fh.write(struct.pack("<II", len(binary), _CHUNK_BIN))
        fh.write(bytes(binary))

    return {
        "buildings": len(tile.buildings),
        "triangles": tile.triangle_count,
        "origin_epsg3008": georeference["origin_epsg3008"],
        "bytes": total,
    }
