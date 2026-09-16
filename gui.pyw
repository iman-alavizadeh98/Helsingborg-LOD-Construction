# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Open the pipeline's window. On Windows, double-click ``Start GUI.bat`` instead.

Imports only the GUI module, which needs nothing beyond Python's standard library.
That way the window still opens when the pipeline's packages are missing, and its
setup checks say what to install — rather than failing before anything is shown.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from run_pipeline.gui import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
