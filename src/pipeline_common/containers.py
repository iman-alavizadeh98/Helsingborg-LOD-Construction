# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Running external tools either in Docker or as a native binary.

Two external tools are driven this way — roofer (Phase 2) and citygml-tools
(CityGML export) — and both follow the same pattern: the whole project root is
bind-mounted into the container at one fixed path, so every file the tool reads
or writes has to be named by its path *inside* the container.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def container_path(root: Path, path: Path, container_root: str | None) -> str:
    """Render ``path`` as the external tool will see it.

    With ``container_root`` set, the path is rebased from the project root on the
    host onto the mount point in the container. Without it (a native binary), it
    is the host path with forward slashes, which every tool here accepts.
    """
    if container_root is None:
        return str(path).replace("\\", "/")
    rel = Path(path).resolve().relative_to(Path(root).resolve())
    return f"{container_root.rstrip('/')}/{rel.as_posix()}"


def tool_command(
    runner: str,
    *,
    root: Path,
    image: str,
    binary: str,
    container_root: str,
) -> tuple[list[str], str | None]:
    """The command prefix for one external tool, and the container root in use.

    Returns ``(prefix, container_root)``. Append the tool's own arguments to
    ``prefix``; render every path argument with :func:`container_path` using the
    returned ``container_root``, which is ``None`` for a native binary.
    """
    if runner == "docker":
        return (
            ["docker", "run", "--rm", "-v", f"{root}:{container_root}", image],
            container_root,
        )
    if runner == "native":
        if shutil.which(binary) is None:
            raise FileNotFoundError(f"'{binary}' not found on PATH")
        return [binary], None
    raise ValueError(f"unknown runner '{runner}': expected 'docker' or 'native'")
