# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""
Buildings footprint pipeline — cadastral attributes, Swedish → English.

Produces the footprint layer the reconstruction pipeline consumes: it reads
Lantmäteriet's national *Byggnad* vector GeoPackage, translates the coded Swedish
attributes, collapses the version history to one row per building, and writes
``buildings_processed_postprocess.gpkg`` (layer ``buildings_postprocess``) — the
file ``config.yml`` names as ``paths.footprints``.

Run it with ``python main.py footprints``.

* ``base``         — abstract load/validate/preprocess/export template
* ``pipeline``     — the Byggnad implementation and the value translators
* ``postprocess``  — newest-row-per-object_id snapshot and its report
* ``translations`` — the Swedish → English lookup tables (constants only)
"""

from .base import BasePipeline
from .pipeline import BuildingsPipeline
from .postprocess import build_postprocess_snapshot

__all__ = ["BasePipeline", "BuildingsPipeline", "build_postprocess_snapshot"]
