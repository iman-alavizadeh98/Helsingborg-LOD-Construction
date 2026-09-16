"""
Post-processing utilities for the buildings pipeline.

Creates an optional postprocess snapshot by removing exact duplicates
and keeping the newest record per object_id.
"""

from pathlib import Path
from typing import Dict, Any, Tuple
from datetime import datetime
import json
import geopandas as gpd


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

    output_gpkg = output_dir / "buildings_processed_postprocess.gpkg"
    latest.to_file(output_gpkg, layer="buildings_postprocess")

    report = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
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
            "gpkg": output_gpkg.name,
            "report_json": "buildings_postprocess_report.json",
            "report_md": "buildings_postprocess_report.md"
        }
    }

    report_json = output_dir / "buildings_postprocess_report.json"
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)

    report_md = output_dir / "buildings_postprocess_report.md"
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
