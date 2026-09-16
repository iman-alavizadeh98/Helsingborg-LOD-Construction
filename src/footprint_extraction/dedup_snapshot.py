# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""
Post-processing for the buildings pipeline — one row per building.

The national Byggnad extract is versioned: the same ``object_id`` can appear
several times, once per revision. Reconstruction needs exactly one polygon per
building, so this collapses the history to the newest row per id.

Called from :meth:`BuildingsPipeline.export`, not separately. Its output —
``buildings_processed_postprocess.gpkg``, layer ``buildings_postprocess`` — is
what ``config.yml`` names as ``paths.footprints``, so it is a required part of
the run rather than an optional extra.
"""

from pathlib import Path
from typing import Dict, Any, Tuple
from datetime import datetime, timezone
import json
import geopandas as gpd

# Output filenames, bound once. They are referenced from three places below —
# the written files, the report body, and the Markdown — and a literal repeated
# in all three drifts silently.
SNAPSHOT_GPKG = "buildings_processed_postprocess.gpkg"
SNAPSHOT_LAYER = "buildings_postprocess"
REPORT_JSON = "buildings_postprocess_report.json"
REPORT_MD = "buildings_postprocess_report.md"


def build_postprocess_snapshot(
    gdf: gpd.GeoDataFrame,
    output_dir: Path,
    id_col: str = "object_id",
    version_col: str = "version_valid_from",
    version_num_col: str = "object_version"
) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
    """
    Create a postprocess snapshot of the dataset.

    Steps:
    1. Drop exact duplicate rows.
    2. Keep the newest record per object_id based on version_valid_from.
       If object_version exists, it is used as a tie-breaker.

    Returns:
        (latest_gdf, report)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if id_col not in gdf.columns:
        raise ValueError(f"Missing id column: {id_col}")
    if version_col not in gdf.columns:
        raise ValueError(f"Missing version column: {version_col}")

    input_rows = int(len(gdf))
    deduped = gdf.drop_duplicates()
    exact_duplicates_removed = input_rows - int(len(deduped))

    duplicate_id_counts = deduped[id_col].value_counts()
    duplicate_object_ids = int((duplicate_id_counts > 1).sum())

    sort_cols = [id_col, version_col]
    if version_num_col in deduped.columns:
        sort_cols.append(version_num_col)

    latest = (
        deduped.sort_values(sort_cols)
        .drop_duplicates(subset=[id_col], keep="last")
    )

    rows_removed_for_postprocess = int(len(deduped)) - int(len(latest))

    output_gpkg = output_dir / SNAPSHOT_GPKG
    latest.to_file(output_gpkg, layer=SNAPSHOT_LAYER)

    report = {
        # Timezone-aware: datetime.utcnow() is deprecated from Python 3.12.
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "rules": [
            "Removed exact duplicate rows.",
            "Kept the newest record per object_id based on version_valid_from and object_version (if available)."
        ],
        "input_rows": input_rows,
        "exact_duplicate_rows_removed": exact_duplicates_removed,
        "duplicate_object_ids": duplicate_object_ids,
        "rows_removed_for_postprocess": rows_removed_for_postprocess,
        "output_rows": int(len(latest)),
        "id_column": id_col,
        "version_column": version_col,
        "version_number_column": version_num_col if version_num_col in deduped.columns else None,
        "sort_columns": sort_cols,
        "output_files": {
            "gpkg": SNAPSHOT_GPKG,
            "layer": SNAPSHOT_LAYER,
            "report_json": REPORT_JSON,
            "report_md": REPORT_MD,
        }
    }

    report_json = output_dir / REPORT_JSON
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)

    report_md = output_dir / REPORT_MD
    report_lines = [
        "# Buildings Postprocess Report",
        "",
        "This report documents the postprocess snapshot creation.",
        "",
        "## Rules",
        "- Removed exact duplicate rows.",
        "- Kept the newest record per object_id based on version_valid_from and object_version (if available).",
        "",
        "## Counts",
        f"- Input rows: {report['input_rows']}",
        f"- Exact duplicate rows removed: {report['exact_duplicate_rows_removed']}",
        f"- Object IDs with multiple versions: {report['duplicate_object_ids']}",
        f"- Rows removed to keep postprocess snapshot: {report['rows_removed_for_postprocess']}",
        f"- Output rows: {report['output_rows']}",
        "",
        "## Columns Used",
        f"- ID column: {report['id_column']}",
        f"- Version column: {report['version_column']}",
        f"- Version number column: {report['version_number_column']}",
        f"- Sort columns: {', '.join(report['sort_columns'])}",
        ""
    ]

    with open(report_md, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    return latest, report
