# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Phase 2 — reconstruct LOD2.2 buildings with roofer.

    python main.py roofer --tile 6204_105

* ``run_roofer`` — writes the roofer TOML from ``config.yml``, runs roofer in
                   Docker or as a native binary, and records the result

roofer runs as a separate process; nothing from it is linked or vendored. Its
output, a CityJSON 2.0 sequence, is the input to ``model_export``.
"""
