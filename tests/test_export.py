# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Regression tests for the model export.

    python tests/test_export.py

Plain asserts and a ``main``, so this runs with no test runner installed.

Uses a synthetic building with known answers rather than a real tile, so it needs
neither the LiDAR data nor Docker: an L-shaped prism (a non-convex roof) placed at
real EPSG:3008 coordinates, plus a single wall with a window-sized hole. The
properties checked are the ones that failed, or could fail, silently:

* the mesh is closed and every edge is shared once in each direction — per-triangle
  winding once flipped sliver triangles and opened cracks in real buildings
* the volume is exactly right, computed after recentring
* merging a sequence offsets every vertex index
* glTF positions, recentred and axis-swapped, come back to real-world coordinates
* PLY keeps real-world coordinates in double precision
"""

import collections
import json
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from model_export.cityjson_sequence import CityJSONSequence, merge_sequence  # noqa: E402
from model_export.gltf_writer import write_glb  # noqa: E402
from model_export.ply_writer import write_ply  # noqa: E402
from model_export.triangulate import (  # noqa: E402
    GROUND, ROOF, WALL, mesh_sequence, triangulate_face,
)

# Real-world placement, so precision problems at 6.2e6 m would show.
X0, Y0, Z0 = 105100.0, 6204600.0, 15.0
SCALE = 0.001
COLOURS = {"RoofSurface": [1, 0, 0], "WallSurface": [0.5, 0.5, 0.5], "GroundSurface": [0.2, 0.2, 0.2]}

# L-shaped footprint, counter-clockwise from above; area 10*4 + 4*6 = 64 m^2.
L_SHAPE = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
HEIGHT = 6.0


def _l_prism_feature(fid: str) -> dict:
    """A closed L-shaped prism as a CityJSONFeature: ground, 6 walls, flat roof."""
    n = len(L_SHAPE)
    verts = [[round(x / SCALE), round(y / SCALE), 0] for x, y in L_SHAPE]
    verts += [[round(x / SCALE), round(y / SCALE), round(HEIGHT / SCALE)] for x, y in L_SHAPE]
    ground = [list(reversed(range(n)))]                  # faces down: clockwise from above
    roof = [list(range(n, 2 * n))]                       # faces up: counter-clockwise
    walls = [[[i, (i + 1) % n, n + (i + 1) % n, n + i]] for i in range(n)]
    shell = [ground, roof, *walls]
    return {
        "type": "CityJSONFeature",
        "id": fid,
        "CityObjects": {
            fid: {"type": "Building", "attributes": {"bid": int(fid)}, "children": [f"{fid}-0"]},
            f"{fid}-0": {
                "type": "BuildingPart", "parents": [fid],
                "geometry": [{
                    "type": "Solid", "lod": "2.2", "boundaries": [shell],
                    "semantics": {
                        "surfaces": [{"type": "GroundSurface"}, {"type": "RoofSurface"},
                                     {"type": "WallSurface"}],
                        "values": [[0, 1] + [2] * n],
                    },
                }],
            },
        },
        "vertices": verts,
    }


def _sequence(features: list[dict]) -> CityJSONSequence:
    header = {
        "type": "CityJSON", "version": "2.0", "vertices": [], "CityObjects": {},
        "transform": {"scale": [SCALE] * 3, "translate": [X0, Y0, Z0]},
        "metadata": {"referenceSystem": "https://www.opengis.net/def/crs/EPSG/0/3008"},
    }
    return CityJSONSequence(header=header, features=features, source=Path("synthetic.city.jsonl"))


def test_face_with_hole_triangulates_without_new_vertices():
    """A 4x4 wall with a 2x2 hole: 8 triangles, using only the ring vertices."""
    verts = np.array([
        [0, 0, 0], [4, 0, 0], [4, 0, 4], [0, 0, 4],        # outer, in the x-z plane
        [1, 0, 1], [1, 0, 3], [3, 0, 3], [3, 0, 1],        # hole, opposite winding
    ], dtype=np.float64) + [X0, Y0, Z0]
    tri = triangulate_face([[0, 1, 2, 3], [4, 5, 6, 7]], verts)
    assert tri.shape == (8, 3), tri.shape
    assert set(tri.ravel()) == set(range(8)), "ear clipping must add no vertices"

    local = verts - verts.mean(axis=0)
    a, b, c = (local[tri[:, k]] for k in range(3))
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum()
    assert abs(area - (16 - 4)) < 1e-6, f"area {area}, expected 12"


def test_sliver_triangles_keep_the_face_winding():
    """A roof edge with millimetre wobble must not crack.

    roofer's roof outlines carry near-collinear vertices, quantised to 1 mm. Ear
    clipping turns them into sliver triangles whose own normal is noise. Deciding
    winding per triangle flipped some of them and opened cracks — two real buildings
    on tile 6204_105. This exact face breaks the per-triangle rule (verified against
    it) and must stay intact with the per-face rule.
    """
    pts = [(0, 0), (7.246, -0.001), (7.268, 0.001), (7.269, 0.002), (8.0, 0.002),
           (8.367, -0.001), (8.588, 0.0), (12, 0), (12, 5), (0, 5)]
    verts = np.array([[X0 + x, Y0 + y, 20 + 0.4 * y] for x, y in pts]).round(3)
    ring = list(range(len(pts)))
    tri = triangulate_face([ring], verts)

    edges = collections.Counter((t[i], t[(i + 1) % 3]) for t in tri for i in range(3))
    boundary = {(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))}
    assert all(edges[e] == 1 for e in boundary), "a boundary edge is missing or reversed"
    internal = {e: n for e, n in edges.items() if e not in boundary}
    assert all(edges[(v, u)] == n for (u, v), n in internal.items()), "a diagonal is unpaired"


def test_mesh_is_closed_oriented_and_has_the_right_volume():
    mesh = mesh_sequence(_sequence([_l_prism_feature("7")]), "2.2")
    assert len(mesh.buildings) == 1 and not mesh.skipped
    b = mesh.buildings[0]

    edges = collections.Counter()
    for t in b.triangles:
        for i in range(3):
            edges[(t[i], t[(i + 1) % 3])] += 1
    assert all(n == 1 for n in edges.values()), "an edge is used twice in one direction"
    assert all(edges[(v, u)] == 1 for (u, v) in edges), "an edge has no opposite partner"

    v = b.vertices - b.vertices.mean(axis=0)
    a, c, d = (v[b.triangles[:, k]] for k in range(3))
    volume = np.einsum("ij,ij->i", a, np.cross(c, d)).sum() / 6.0
    assert abs(volume - 64 * HEIGHT) < 1e-6, f"volume {volume}, expected {64 * HEIGHT}"

    # L-shaped roof and ground are non-convex: 6 vertices -> 4 triangles each.
    assert (b.semantics == ROOF).sum() == 4
    assert (b.semantics == GROUND).sum() == 4
    assert (b.semantics == WALL).sum() == 12


def test_building_without_lod_geometry_is_reported_not_dropped():
    feature = _l_prism_feature("9")
    feature["CityObjects"]["9-0"]["geometry"][0]["lod"] = "1.2"
    mesh = mesh_sequence(_sequence([feature]), "2.2")
    assert not mesh.buildings
    assert mesh.skipped == [{"building": "9", "reason": "no_lod22_geometry"}]


def test_merge_offsets_vertex_indices():
    doc = merge_sequence(_sequence([_l_prism_feature("1"), _l_prism_feature("2")]))
    assert len(doc["vertices"]) == 24
    shell_2 = doc["CityObjects"]["2-0"]["geometry"][0]["boundaries"][0]
    indices = {i for face in shell_2 for ring in face for i in ring}
    assert indices == set(range(12, 24)), "second feature's indices must be offset by 12"
    lo, hi = doc["metadata"]["geographicalExtent"][:3], doc["metadata"]["geographicalExtent"][3:]
    assert np.allclose(lo, [X0, Y0, Z0]) and np.allclose(hi, [X0 + 10, Y0 + 10, Z0 + HEIGHT])


def test_gltf_round_trips_to_real_world_coordinates():
    mesh = mesh_sequence(_sequence([_l_prism_feature("7")]), "2.2")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.glb"
        write_glb(mesh, path, tile_id="t", colours=COLOURS)
        data = path.read_bytes()

    magic, version, total = struct.unpack_from("<III", data, 0)
    assert (magic, version, total) == (0x46546C67, 2, len(data))
    jlen = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + jlen])
    binary = data[28 + jlen:]

    origin = np.array(gltf["nodes"][0]["extras"]["georeference"]["origin_epsg3008"])
    acc = gltf["accessors"][gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    view = gltf["bufferViews"][acc["bufferView"]]
    p = np.frombuffer(binary, "<f4", acc["count"] * 3, view["byteOffset"]).reshape(-1, 3)
    real = np.column_stack((p[:, 0], -p[:, 2], p[:, 1])).astype(np.float64) + origin

    assert np.abs(real - mesh.buildings[0].vertices).max() < 1e-3, "glTF lost more than 1 mm"
    assert {m["name"] for m in gltf["materials"]} == {"GroundSurface", "RoofSurface", "WallSurface"}


def test_ply_keeps_real_world_double_coordinates():
    mesh = mesh_sequence(_sequence([_l_prism_feature("7")]), "2.2")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.ply"
        write_ply(mesh, path, tile_id="t", colours=COLOURS)
        data = path.read_bytes()

    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii")
    assert "property double x" in header and "property int building" in header
    v = np.frombuffer(data, "<f8", 12 * 3, end).reshape(-1, 3)
    assert np.array_equal(v, mesh.buildings[0].vertices), "PLY must not recentre or round"
    assert v[:, 1].min() > 6_000_000, "coordinates must be real-world, not local"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
