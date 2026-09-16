# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Inspect and repair reconstructed models.

    python main.py inspect --tile 6204_105

* ``inspect_cityjson`` — LoDs, semantic surfaces, roof forms, volume and height
                         statistics for a tile's CityJSON
* ``repair_cityjson``  — standalone viewer aid: strips bare ``NaN`` so strict JSON
                         parsers accept a file
"""
