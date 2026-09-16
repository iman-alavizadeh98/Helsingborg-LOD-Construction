"""QA records.

Convention: every pipeline stage writes a QA record with counts in, counts out
and failures. Records accumulate into one per-tile JSON plus a readable
Markdown summary.
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

    def write(self) -> tuple[Path, Path]:
        data = self.to_dict()
        json_path = self.qa_dir / f"{self.tile_id}_qa.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        md_path = self.qa_dir / f"{self.tile_id}_qa.md"
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(self._markdown(data))
        return json_path, md_path

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
                    add(f"| {k} | {_fmt(v)} |")
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
                    add("| " + " | ".join(_fmt(f.get(k, "")) for k in keys) + " |")
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


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.3f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:.3e}"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}={_fmt(x)}" for k, x in v.items())
    return str(v)
