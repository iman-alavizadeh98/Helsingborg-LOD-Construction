# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""QA records.

Convention: every pipeline stage writes a QA record with counts in, counts out
and failures. Records accumulate into one report per tile, written three ways
from the same data:

* ``<tile>_qa.json`` — the complete machine-readable record
* ``<tile>_qa.md``   — plain-text summary, good in a diff or a code review
* ``<tile>_qa.html`` — the same content for a browser; see ``qa_report_html``
"""

from __future__ import annotations

import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def _jsonable(obj: Any) -> Any:
    """Coerce numpy scalars/arrays and Paths into JSON-serialisable values."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return value if np.isfinite(value) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return obj if np.isfinite(obj) else None
    return obj


class StageRecord:
    """Counts in, counts out and failures for a single stage."""

    def __init__(self, name: str):
        self.name = name
        self.counts_in: dict[str, Any] = {}
        self.counts_out: dict[str, Any] = {}
        self.metrics: dict[str, Any] = {}
        self.failures: list[dict[str, Any]] = []
        self.outputs: list[str] = []
        self._t0 = time.perf_counter()
        self.seconds: float | None = None

    def count_in(self, **kwargs: Any) -> "StageRecord":
        self.counts_in.update(kwargs)
        return self

    def count_out(self, **kwargs: Any) -> "StageRecord":
        self.counts_out.update(kwargs)
        return self

    def metric(self, **kwargs: Any) -> "StageRecord":
        self.metrics.update(kwargs)
        return self

    def failure(self, kind: str, **detail: Any) -> "StageRecord":
        self.failures.append({"kind": kind, **detail})
        return self

    def output(self, path: Path | str) -> "StageRecord":
        self.outputs.append(str(path))
        return self

    def finish(self) -> "StageRecord":
        if self.seconds is None:
            self.seconds = round(time.perf_counter() - self._t0, 3)
        return self

    def to_dict(self) -> dict[str, Any]:
        self.finish()
        return _jsonable(
            {
                "stage": self.name,
                "seconds": self.seconds,
                "counts_in": self.counts_in,
                "counts_out": self.counts_out,
                "metrics": self.metrics,
                "failures": self.failures,
                "outputs": self.outputs,
            }
        )


class TileQA:
    """Accumulates stage records for one tile and writes the report."""

    def __init__(self, tile_id: str, qa_dir: Path, config: dict[str, Any] | None = None):
        self.tile_id = tile_id
        self.qa_dir = Path(qa_dir)
        self.qa_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or {}
        self.stages: list[StageRecord] = []
        self.started = datetime.now(timezone.utc)

    def stage(self, name: str) -> StageRecord:
        rec = StageRecord(name)
        self.stages.append(rec)
        return rec

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(
            {
                "tile_id": self.tile_id,
                "started_utc": self.started.isoformat(),
                "finished_utc": datetime.now(timezone.utc).isoformat(),
                "platform": {
                    "python": platform.python_version(),
                    "system": platform.system(),
                },
                "config": self.config,
                "stages": [s.to_dict() for s in self.stages],
            }
        )

    # -- writing -----------------------------------------------------------

    def write(self) -> tuple[Path, Path, Path]:
        """Write the tile's report, merged with whatever earlier stages recorded.

        Each phase runs as its own process and builds its own ``TileQA``, but they
        all share one report per tile. Writing this run's stages on their own used
        to replace the file wholesale, so running roofer erased every Phase 1
        stage — the report ended up describing only the last command run. Now a
        stage name that appears in this run replaces its earlier record, and every
        other stage already on disk is kept; stages are then ordered by phase.

        Returns the paths of the JSON, Markdown and HTML reports.
        """
        # Imported here, not at module scope: the HTML renderer reuses this
        # module's value formatter, and a top-level import would be circular.
        from .qa_report_html import render_html

        json_path = self.qa_dir / f"{self.tile_id}_qa.json"
        data = self._merge_with_existing(self.to_dict(), json_path)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        md_path = self.qa_dir / f"{self.tile_id}_qa.md"
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(self._markdown(data))
        html_path = self.qa_dir / f"{self.tile_id}_qa.html"
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(render_html(data, self.qa_dir))
        return json_path, md_path, html_path

    @staticmethod
    def _merge_with_existing(data: dict[str, Any], json_path: Path) -> dict[str, Any]:
        """Fold this run's record into the one already on disk, if any."""
        if not json_path.is_file():
            return data
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                previous = json.load(fh)
        except (OSError, ValueError):
            # An unreadable earlier record is not worth failing a run over; it is
            # replaced, exactly as it would have been before merging existed.
            return data

        fresh = {s["stage"]: s for s in data["stages"]}
        stages = [fresh.pop(s["stage"], s) for s in previous.get("stages", [])]
        stages.extend(fresh.values())
        # Keep the report in pipeline order whichever phase ran last. Stage names
        # start with their phase ("0-load", "1.2-recover", "2-roofer", "3-export");
        # the sort is stable, so stages within a phase keep their execution order.
        stages.sort(key=_phase_of)

        merged = dict(data)
        merged["stages"] = stages
        merged["started_utc"] = previous.get("started_utc", data["started_utc"])
        merged["config"] = {**previous.get("config", {}), **data["config"]}
        return merged

    def _markdown(self, data: dict[str, Any]) -> str:
        lines: list[str] = []
        add = lines.append
        add(f"# QA report — tile `{self.tile_id}`")
        add("")
        add(f"Generated {data['finished_utc']}")
        add("")

        total = sum(s.get("seconds") or 0.0 for s in data["stages"])
        n_fail = sum(len(s["failures"]) for s in data["stages"])
        add(f"**Stages:** {len(data['stages'])} &nbsp;|&nbsp; "
            f"**Runtime:** {total:.1f} s &nbsp;|&nbsp; "
            f"**Flagged:** {n_fail}")
        add("")

        for stage in data["stages"]:
            add(f"## {stage['stage']}")
            add("")
            add(f"_{stage['seconds']:.2f} s_" if stage["seconds"] is not None else "")
            add("")
            for title, block in (
                ("Counts in", stage["counts_in"]),
                ("Counts out", stage["counts_out"]),
                ("Metrics", stage["metrics"]),
            ):
                if not block:
                    continue
                add(f"**{title}**")
                add("")
                add("| key | value |")
                add("|---|---|")
                for k, v in block.items():
                    add(f"| {k} | {_fmt_field(k, v)} |")
                add("")
            if stage["failures"]:
                add(f"**Flagged ({len(stage['failures'])})**")
                add("")
                shown = stage["failures"][:20]
                keys: list[str] = []
                for f in shown:
                    for k in f:
                        if k not in keys:
                            keys.append(k)
                add("| " + " | ".join(keys) + " |")
                add("|" + "|".join("---" for _ in keys) + "|")
                for f in shown:
                    add("| " + " | ".join(_fmt_field(k, f.get(k, "")) for k in keys) + " |")
                if len(stage["failures"]) > len(shown):
                    add("")
                    add(f"_… {len(stage['failures']) - len(shown)} more in the JSON record._")
                add("")
            if stage["outputs"]:
                add("**Outputs**")
                add("")
                for o in stage["outputs"]:
                    add(f"- `{o}`")
                add("")
        return "\n".join(lines) + "\n"


def _phase_of(stage: dict[str, Any]) -> int:
    """The phase number a stage name starts with; unnumbered stages sort last."""
    head = str(stage.get("stage", "")).split("-", 1)[0].split(".", 1)[0]
    return int(head) if head.isdigit() else 99


# Keys whose integer values are identifiers or codes, not quantities. Formatting
# them as numbers printed building 1074 as "1,074".
_ID_KEYS = {"bid", "building", "building_id", "exit_code"}


def _fmt_field(key: str, v: Any) -> str:
    """Format a value, knowing which field it belongs to."""
    if key in _ID_KEYS and isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    return _fmt(v)


def _fmt(v: Any) -> str:
    """Format one value for a human-readable report (Markdown or HTML)."""
    if v is None:
        return "—"
    # bool is a subclass of int: test it first, or True prints as "1".
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        if abs(v) >= 1e6:
            # Coordinates. Scientific notation turned 6204507.44 into "6.205e+06",
            # which hid the very position the extent is there to show.
            return f"{v:,.2f}"
        if v != 0 and abs(v) < 1e-3:
            return f"{v:.3e}"
        return f"{v:,.3f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}={_fmt(x)}" for k, x in v.items())
    return str(v)
