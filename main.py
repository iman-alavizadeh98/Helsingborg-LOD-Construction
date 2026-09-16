#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Run the pipeline straight from a clone, with nothing installed.

    python main.py all --tile 6204_105

The commands live in :mod:`pipeline.cli`; this file only puts ``src/`` on the
import path first. Installing the project (``pip install -e .``) gives the same
commands as ``helsingborg-lod22`` and makes this shim unnecessary — it stays
because a customer should be able to clone and run without installing anything.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pipeline.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
