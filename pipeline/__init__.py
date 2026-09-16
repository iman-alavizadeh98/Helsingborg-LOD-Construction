# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""LOD2.2 building reconstruction pipeline for Helsingborg.

Stages follow PROJECT_PLAN.md:

* ``dtm``        — 1.1 ground raster
* ``recover``    — 1.2 overlap-class recovery
* ``footprints`` — 1.3 footprint/roofprint offset and buffer sweep
* ``tiling``     — 1.5 common grid with buffer overlap

Everything is EPSG:3008 end to end; no stage translates to a local frame.
"""

from .config import Config, load_config

__all__ = ["Config", "load_config"]
__version__ = "0.1.0"
