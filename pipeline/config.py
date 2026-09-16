# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Configuration loading and path resolution.

Every path in the pipeline is resolved through here against ``paths.root`` so
no stage ever holds a hardcoded path.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_NAME = "config.yml"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tile:
    """One tile of work: an id and the LAS file backing it."""

    id: str
    las: Path


class Config:
    """Parsed ``config.yml`` with resolved, absolute paths."""

    def __init__(self, data: dict[str, Any], config_path: Path):
        self._data = data
        self.config_path = config_path
        # Relative paths in the config resolve against the config file's own
        # directory, so the pipeline runs the same from any working directory.
        base = config_path.parent
        self.root = (base / data.get("paths", {}).get("root", ".")).resolve()

    # -- access ------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def section(self, name: str) -> dict[str, Any]:
        value = self._data.get(name)
        if not isinstance(value, dict):
            raise ConfigError(f"config section '{name}' is missing or not a mapping")
        return value

    def as_dict(self) -> dict[str, Any]:
        """Deep copy, safe to embed in a QA record."""
        return copy.deepcopy(self._data)

    # -- paths -------------------------------------------------------------

    def path(self, *parts: str) -> Path:
        """Resolve a path relative to the project root."""
        return (self.root / Path(*parts)).resolve()

    def _paths(self) -> dict[str, Any]:
        return self.section("paths")

    @property
    def crs(self) -> str:
        return self.section("project")["crs"]

    @property
    def out_dir(self) -> Path:
        return self.path(self._paths().get("out_dir", "out"))

    @property
    def work_dir(self) -> Path:
        return self.path(self._paths().get("work_dir", "out/work"))

    @property
    def qa_dir(self) -> Path:
        return self.path(self._paths().get("qa_dir", "out/qa"))

    @property
    def footprints_path(self) -> Path:
        return self.path(self._paths()["footprints"])

    @property
    def footprints_layer(self) -> str | None:
        return self._paths().get("footprints_layer")

    @property
    def footprints_crs(self) -> str | None:
        return self._paths().get("footprints_crs")

    def tile_dir(self, tile_id: str) -> Path:
        """Per-tile working directory, created on demand."""
        d = self.work_dir / tile_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- tiles -------------------------------------------------------------

    def tiles(self) -> list[Tile]:
        las_dir = self._paths().get("las_dir", ".")
        out = []
        for entry in self.get("tiles", []) or []:
            out.append(
                Tile(id=str(entry["id"]), las=self.path(las_dir, entry["las"]))
            )
        return out

    def tile(self, tile_id: str) -> Tile:
        for t in self.tiles():
            if t.id == tile_id:
                return t
        known = ", ".join(t.id for t in self.tiles()) or "(none)"
        raise ConfigError(f"unknown tile '{tile_id}'; configured tiles: {known}")


def load_config(path: str | Path | None = None) -> Config:
    """Load ``config.yml``, searching upward from the CWD if not given."""
    if path is not None:
        config_path = Path(path).resolve()
        if not config_path.is_file():
            raise ConfigError(f"config file not found: {config_path}")
    else:
        config_path = _find_config()

    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} did not parse to a mapping")
    return Config(data, config_path)


def _find_config() -> Path:
    """Walk up from the CWD, then fall back to the package's parent."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / DEFAULT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    fallback = Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_NAME
    if fallback.is_file():
        return fallback
    raise ConfigError(
        f"no {DEFAULT_CONFIG_NAME} found in the working directory or any parent"
    )
