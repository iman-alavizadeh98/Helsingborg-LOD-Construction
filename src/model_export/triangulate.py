# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Turn CityJSON surfaces into triangle meshes, keeping their semantics.

glTF and PLY store triangles; CityJSON stores planar polygons that may be
non-convex (L-shaped roofs) and may have holes. Each polygon is triangulated
separately, and every triangle carries the semantic class of the surface it came
from, so the mesh formats can still tell roof from wall from ground.

**Why ear clipping.** It triangulates the polygon itself, holes included, and
adds no vertices. That matters for a watertight model: a method that inserts
points on an edge, or triangulates the convex hull as ``scipy.spatial.Delaunay``
does, leaves the wall next to it without a matching vertex — a T-junction, and a
visible crack. The project plan rules Delaunay out for this reason.

This is serialisation of roofer's output, not reconstruction: no surface is
moved, merged, simplified or invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

import mapbox_earcut
import numpy as np

from .cityjson_sequence import CityJSONSequence

# Semantic classes, as a compact per-triangle code. roofer emits the first three;
# anything else, or a surface without semantics, is kept as OTHER, never dropped.
GROUND, WALL, ROOF, OTHER = 0, 1, 2, 3
SEMANTIC_NAMES = ("GroundSurface", "WallSurface", "RoofSurface", "Other")
_CODE_BY_NAME = {name: code for code, name in enumerate(SEMANTIC_NAMES[:3])}

# A face whose polygon area is below this (in m^2) is degenerate: it has no
# well-defined plane to project onto and contributes nothing visible.
_MIN_FACE_AREA = 1e-6


@dataclass
class BuildingMesh:
    """One building as triangles, in real-world EPSG:3008 coordinates."""

    building_id: str
    attributes: dict[str, Any]
    vertices: np.ndarray    # (N, 3) float64, real-world coordinates
    triangles: np.ndarray   # (M, 3) int64, indices into `vertices`
    semantics: np.ndarray   # (M,) uint8, one of GROUND / WALL / ROOF / OTHER


@dataclass
class TileMesh:
    """Every building in a tile that has geometry at the requested LoD."""

    lod: str
    crs: str | None
    buildings: list[BuildingMesh] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    degenerate_faces: int = 0

    @property
    def triangle_count(self) -> int:
        return int(sum(len(b.triangles) for b in self.buildings))

    @property
    def vertex_count(self) -> int:
        return int(sum(len(b.vertices) for b in self.buildings))

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        stacked = np.vstack([b.vertices for b in self.buildings])
        return stacked.min(axis=0), stacked.max(axis=0)


def _faces(geom: dict[str, Any]) -> Iterator[tuple[list[list[int]], int]]:
    """Yield ``(rings, semantic_code)`` for every surface of a geometry.

    Flattens the geometry-type-specific nesting — MultiSurface, Solid and
    MultiSolid nest surfaces at different depths, and ``semantics.values`` mirrors
    that nesting one level shallower than the boundaries.
    """
    gtype = geom["type"]
    semantics = geom.get("semantics") or {}
    surfaces = semantics.get("surfaces", [])
    values = semantics.get("values")

    def code(value: int | None) -> int:
        if value is None or value >= len(surfaces):
            return OTHER
        return _CODE_BY_NAME.get(surfaces[value].get("type"), OTHER)

    def walk_surfaces(faces, vals):
        for i, rings in enumerate(faces):
            yield rings, code(vals[i] if vals is not None else None)

    if gtype in ("MultiSurface", "CompositeSurface"):
        yield from walk_surfaces(geom["boundaries"], values)
    elif gtype == "Solid":
        for s, shell in enumerate(geom["boundaries"]):
            yield from walk_surfaces(shell, values[s] if values is not None else None)
    elif gtype in ("MultiSolid", "CompositeSolid"):
        for d, solid in enumerate(geom["boundaries"]):
            for s, shell in enumerate(solid):
                vals = values[d][s] if values is not None else None
                yield from walk_surfaces(shell, vals)
    # Point and line geometries have no surfaces to triangulate.


def triangulate_face(rings: list[list[int]], vertices: np.ndarray) -> np.ndarray:
    """Triangulate one planar polygon with holes; returns ``(K, 3)`` vertex indices.

    The indices refer to ``vertices`` directly, so triangles share the original
    CityJSON vertices and adjacent faces stay connected.

    Triangles are wound to match the polygon's own orientation. CityJSON orders a
    face's outer ring counter-clockwise seen from outside the solid; ear clipping
    in a projected 2D frame knows nothing of that, so the whole face is flipped if
    its triangles point inward.

    The decision is made once per face, never per triangle. Ear clipping winds all
    of a face's triangles the same way, but a sliver triangle — three nearly
    collinear vertices, common on roofer's roofs — has a normal dominated by the
    1 mm vertex quantisation and can point either way. Judging triangles one by
    one flipped such slivers individually and opened cracks in otherwise closed
    solids; on tile 6204_105 that broke two of 61 buildings.
    """
    if not rings or len(rings[0]) < 3:
        return np.empty((0, 3), dtype=np.int64)

    index = np.fromiter((i for ring in rings for i in ring), dtype=np.int64)
    points = vertices[index]
    # Recentre on the face before any arithmetic: at 6.2e6 m, products of raw
    # coordinates lose the precision the area and normal depend on.
    local = points - points.mean(axis=0)

    # Newell's method: a robust normal for any simple polygon, convex or not.
    outer = local[: len(rings[0])]
    nxt = np.roll(outer, -1, axis=0)
    normal = np.array([
        np.sum((outer[:, 1] - nxt[:, 1]) * (outer[:, 2] + nxt[:, 2])),
        np.sum((outer[:, 2] - nxt[:, 2]) * (outer[:, 0] + nxt[:, 0])),
        np.sum((outer[:, 0] - nxt[:, 0]) * (outer[:, 1] + nxt[:, 1])),
    ])
    if 0.5 * np.linalg.norm(normal) < _MIN_FACE_AREA:
        return np.empty((0, 3), dtype=np.int64)

    # Project by dropping the dominant normal axis: exact, and never degenerate
    # for a polygon with non-zero area.
    uv = np.delete(local, int(np.argmax(np.abs(normal))), axis=1)
    ring_ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    tri_local = mapbox_earcut.triangulate_float64(uv, ring_ends).astype(np.int64).reshape(-1, 3)
    if tri_local.size == 0:
        return np.empty((0, 3), dtype=np.int64)

    a, b, c = (local[tri_local[:, k]] for k in range(3))
    # Area-weighted sum of triangle normals: large triangles dominate, so slivers
    # cannot swing the decision.
    if np.cross(b - a, c - a).sum(axis=0) @ normal < 0:
        tri_local = tri_local[:, [0, 2, 1]]
    return index[tri_local]


def mesh_sequence(seq: CityJSONSequence, lod: str = "2.2") -> TileMesh:
    """Triangulate every building's geometry at ``lod``.

    A building with no geometry at that LoD — roofer marks those where it found no
    usable points — is recorded in ``skipped`` with a reason, not silently omitted.
    """
    lod = str(lod)
    tile = TileMesh(lod=lod, crs=seq.crs)

    for feature in seq.features:
        fid = str(feature.get("id"))
        objects = feature["CityObjects"]
        root = objects.get(fid) or next(
            (o for o in objects.values() if not o.get("parents")), {}
        )
        vertices = seq.real_vertices(feature)

        triangles: list[np.ndarray] = []
        semantics: list[np.ndarray] = []
        for obj in objects.values():
            for geom in obj.get("geometry", []):
                if str(geom.get("lod")) != lod:
                    continue
                for rings, code in _faces(geom):
                    tri = triangulate_face(rings, vertices)
                    if len(tri) == 0:
                        tile.degenerate_faces += 1
                        continue
                    triangles.append(tri)
                    semantics.append(np.full(len(tri), code, dtype=np.uint8))

        if not triangles:
            tile.skipped.append({"building": fid, "reason": f"no_lod{lod.replace('.', '')}_geometry"})
            continue

        tri = np.vstack(triangles)
        # Keep only the vertices this LoD uses: the feature also holds the LoD 0
        # footprint's vertices, which would otherwise ride along unreferenced.
        used, remapped = np.unique(tri, return_inverse=True)
        tile.buildings.append(BuildingMesh(
            building_id=fid,
            attributes=root.get("attributes", {}),
            vertices=vertices[used],
            triangles=remapped.reshape(tri.shape).astype(np.int64),
            semantics=np.concatenate(semantics),
        ))
    return tile
