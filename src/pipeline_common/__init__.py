# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Shared by every pipeline: the config loader and the QA record.

* ``config``    — loads ``config.yml``; every path resolves against the config
                  file's own directory, so commands work from anywhere
* ``qa_record`` — per-tile QA record: counts in, counts out, metrics, failures

Nothing here knows about point clouds, footprints or roofer. If a module needs
one of those, it belongs in the pipeline that owns it.
"""

from .config import Config, ConfigError, load_config

__all__ = ["Config", "ConfigError", "load_config"]
