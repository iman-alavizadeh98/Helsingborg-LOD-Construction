# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Phase 1 — turn a raw LiDAR tile and cadastral footprints into roofer inputs.

    python main.py prepare --tile 6204_105

Most of the output quality is decided here, not in roofer.

* ``readers``             — LAS and footprint loading, EPSG:3008 end to end
* ``dtm``                 — 1.1 gap-filled 0.5 m terrain raster
* ``overlap_recovery``    — 1.2 roof points from classes 1 and 12, by height, not label
* ``roofprint_offset``    — 1.3 footprint → roofprint offset and buffer sweep
* ``footprint_diagnosis`` — 1.4 why a footprint has no roof points
* ``tiling``              — 1.5 core / buffered extents and building ownership
* ``prepare_tile``        — the driver: runs the above, writes the prepared LAS,
                            buffered roofprints and DTM

Everything is EPSG:3008 end to end; no stage translates to a local frame.
"""
