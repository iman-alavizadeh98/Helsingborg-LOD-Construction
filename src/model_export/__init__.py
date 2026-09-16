# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Export reconstructed buildings as CityJSON, CityGML, glTF and PLY.

    python main.py export --tile 6204_105

roofer's CityJSON sequence is the single source; every format is converted from
it, so all of them describe identical geometry.

* ``cityjson_sequence`` — read the sequence; merge it into one ``.city.json``
* ``citygml``           — CityJSON → CityGML 2.0/3.0 via citygml-tools
* ``triangulate``       — planar faces → triangles, keeping roof/wall/ground
* ``gltf_writer``       — binary glTF 2.0, recentred (float32) and Y-up
* ``ply_writer``        — binary PLY in real-world double coordinates
* ``export_models``     — the driver
"""
