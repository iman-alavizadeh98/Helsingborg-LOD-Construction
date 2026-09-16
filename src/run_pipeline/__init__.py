# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Command-line entry point for every pipeline.

    python main.py all --tile 6204_105

The commands live in ``cli``. This package only dispatches: each stage keeps its
own ``main(argv) -> int`` in the pipeline package that owns it.
"""
