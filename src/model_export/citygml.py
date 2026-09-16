# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Convert the merged CityJSON to CityGML with citygml-tools.

CityGML is not written here by hand. ``citygml-tools`` (citygml4j project,
Apache-2.0) is the reference CityJSON ↔ CityGML converter, and it runs the same
way roofer does — in its official Docker image, or as a native install — so it
adds no Python dependency and no Java unless you choose the native route.

It reads a plain CityJSON file, not roofer's ``.city.jsonl`` sequence, which is
why the CityGML export always goes through the merged ``<tile>.city.json``.

Verified on tile 6204_105 with CityGML 2.0: 66 ``bldg:Building`` with LoD 0
footprints, 61 ``bldg:BuildingPart`` with ``lod2Solid``, every roof, wall and
ground polygon carried over as ``RoofSurface`` / ``WallSurface`` /
``GroundSurface``, ``srsName`` EPSG:3008. CityJSON LoD 2.2 maps to CityGML LoD 2,
which has no sub-levels.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from pipeline_common.config import Config
from pipeline_common.containers import container_path, tool_command

SUPPORTED_VERSIONS = ("2.0", "3.0")


def convert_to_citygml(
    cfg: Config,
    cityjson_path: Path,
    out_dir: Path,
    gcfg: dict[str, Any],
    log_path: Path,
) -> dict[str, Any]:
    """Run citygml-tools ``from-cityjson`` on one file.

    Returns the command, exit code and the written ``.city.gml`` path (``None`` if
    nothing was produced). The tool's full output goes to ``log_path``.
    """
    version = str(gcfg.get("version", "2.0"))
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(
            f"export.citygml.version must be one of {SUPPORTED_VERSIONS}, got {version!r}"
        )

    prefix, container_root = tool_command(
        str(gcfg.get("runner", "docker")),
        root=cfg.root,
        image=str(gcfg.get("image", "citygml4j/citygml-tools:2.5.0")),
        binary=str(gcfg.get("binary", "citygml-tools")),
        container_root=str(gcfg.get("container_root", "/work")),
    )
    cmd = prefix + [
        "from-cityjson",
        container_path(cfg.root, cityjson_path, container_root),
        "--citygml-version", version,
        "--output", container_path(cfg.root, out_dir, container_root),
    ]

    # citygml-tools names its output after the input: <tile>.city.json -> <tile>.city.gml.
    expected = out_dir / (cityjson_path.name[: -len(".json")] + ".gml")
    if expected.exists():
        expected.unlink()   # so a failed run cannot leave the previous file looking fresh

    proc = subprocess.run(cmd, capture_output=True, text=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"$ {' '.join(cmd)}\n\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
        encoding="utf-8",
    )
    return {
        "command": cmd,
        "exit_code": proc.returncode,
        "output": expected if expected.is_file() else None,
        "citygml_version": version,
        "log": log_path,
    }
