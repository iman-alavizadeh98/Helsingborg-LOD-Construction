# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Read roofer's CityJSON sequence, and merge it into one CityJSON file.

roofer writes a *CityJSON Text Sequence* (``.city.jsonl``): the first line is a
``CityJSON`` header carrying the CRS and the vertex ``transform``, and every
following line is a self-contained ``CityJSONFeature`` — one building. That form
streams well, but a good deal of tooling only reads a plain CityJSON document,
citygml-tools among them. So the sequence is the source of every export, and the
merged ``.city.json`` is both a deliverable and the input to the CityGML step.

Merging is mechanical. Each feature's vertex indices are local to that feature,
so they are offset by the number of vertices already written. All features share
the header's ``transform``, so the quantised integer vertices are copied as they
are — no coordinate is rounded again, and none is moved to a local frame.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from model_inspection.repair_cityjson import fix_document

# Features using these carry references that a plain vertex-index offset would
# corrupt. roofer 1.0.0 emits neither; fail loudly rather than write a broken file
# if a future version starts to.
_UNSUPPORTED_FEATURE_KEYS = ("appearance", "geometry-templates")


@dataclass
class CityJSONSequence:
    """A parsed CityJSON Text Sequence: one header plus one feature per building."""

    header: dict[str, Any]
    features: list[dict[str, Any]]
    source: Path

    @property
    def scale(self) -> np.ndarray:
        return np.asarray(self.header["transform"]["scale"], dtype=np.float64)

    @property
    def translate(self) -> np.ndarray:
        return np.asarray(self.header["transform"]["translate"], dtype=np.float64)

    @property
    def crs(self) -> str | None:
        """The CRS as ``EPSG:<code>``, from the header's reference-system URL."""
        url = self.header.get("metadata", {}).get("referenceSystem")
        if not url:
            return None
        code = url.rstrip("/").rsplit("/", 1)[-1]
        return f"EPSG:{code}" if code.isdigit() else url

    def real_vertices(self, feature: dict[str, Any]) -> np.ndarray:
        """A feature's vertices as float64 real-world coordinates, ``(N, 3)``."""
        ints = np.asarray(feature["vertices"], dtype=np.float64).reshape(-1, 3)
        return ints * self.scale + self.translate


def read_sequence(path: Path | str) -> CityJSONSequence:
    """Parse a ``.city.jsonl`` file, checking it is the shape roofer writes."""
    path = Path(path)
    header: dict[str, Any] | None = None
    features: list[dict[str, Any]] = []

    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if header is None:
                if obj.get("type") != "CityJSON":
                    raise ValueError(
                        f"{path.name}:{lineno}: a CityJSON sequence must start with a "
                        f"'CityJSON' header, found type {obj.get('type')!r}"
                    )
                if "transform" not in obj:
                    raise ValueError(f"{path.name}: header has no 'transform'")
                header = obj
                continue
            if obj.get("type") != "CityJSONFeature":
                raise ValueError(
                    f"{path.name}:{lineno}: expected 'CityJSONFeature', "
                    f"found {obj.get('type')!r}"
                )
            features.append(obj)

    if header is None:
        raise ValueError(f"{path.name} is empty")
    return CityJSONSequence(header=header, features=features, source=path)


def _offset_boundaries(boundaries: Any, offset: int) -> Any:
    """Add ``offset`` to every vertex index in an arbitrarily nested boundary.

    Boundary nesting depth depends on the geometry type (a Solid is shells →
    surfaces → rings → indices, a MultiSurface one level less), but every integer
    in it is a vertex index, so one recursion covers all of them.
    """
    if isinstance(boundaries, list):
        return [_offset_boundaries(b, offset) for b in boundaries]
    return boundaries + offset


def merge_sequence(seq: CityJSONSequence) -> dict[str, Any]:
    """One CityJSON document holding every feature of the sequence."""
    header = seq.header
    doc: dict[str, Any] = {
        "type": "CityJSON",
        "version": header.get("version", "2.0"),
        "transform": header["transform"],
        "metadata": dict(header.get("metadata", {})),
        "CityObjects": {},
        "vertices": [],
    }
    if "extensions" in header:
        doc["extensions"] = header["extensions"]

    for feature in seq.features:
        unsupported = [k for k in _UNSUPPORTED_FEATURE_KEYS if k in feature]
        if unsupported:
            raise NotImplementedError(
                f"feature {feature.get('id')!r} uses {unsupported}; merging those "
                f"needs index remapping this exporter does not implement"
            )

        offset = len(doc["vertices"])
        for oid, obj in feature["CityObjects"].items():
            if oid in doc["CityObjects"]:
                raise ValueError(f"city object id {oid!r} appears in two features")
            geometries = []
            for geom in obj.get("geometry", []):
                if geom.get("type") == "GeometryInstance":
                    raise NotImplementedError(
                        f"{oid!r} uses a GeometryInstance; templates are not supported"
                    )
                geometries.append(
                    {**geom, "boundaries": _offset_boundaries(geom["boundaries"], offset)}
                )
            doc["CityObjects"][oid] = {**obj, "geometry": geometries} if "geometry" in obj else obj
        doc["vertices"].extend(feature["vertices"])

    # The header's extent covers x and y only (roofer writes z as 0 to 0); with
    # every vertex now in one place, the true 3D extent is cheap to compute.
    if doc["vertices"]:
        real = np.asarray(doc["vertices"], dtype=np.float64) * seq.scale + seq.translate
        doc["metadata"]["geographicalExtent"] = [
            *(float(v) for v in real.min(axis=0)),
            *(float(v) for v in real.max(axis=0)),
        ]
    return doc


def write_cityjson(doc: dict[str, Any], path: Path | str) -> dict[str, int]:
    """Write a CityJSON document as strict JSON.

    Python's ``json`` happily emits bare ``NaN``, which is not JSON and makes strict
    parsers reject the whole file. Non-finite attribute values are dropped first,
    using the same repair ``model_inspection.repair_cityjson`` applies by hand.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = {"nonfinite": 0, "lod": 0, "lines": 0}
    clean = fix_document(doc, None, stats)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    return {
        "city_objects": len(clean["CityObjects"]),
        "vertices": len(clean["vertices"]),
        "nonfinite_values_dropped": stats["nonfinite"],
    }
