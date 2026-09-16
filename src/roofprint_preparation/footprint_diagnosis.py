# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Per-footprint failure catalogue.

"Footprint with no points" is not one problem. On the sample tile it resolved
into four distinct causes with different remedies, so the QA report names the
cause rather than just counting the symptom. Phase 3 wants failures catalogued
by building type; this is where that catalogue comes from.

Reasons emitted:

``ok``                      roof points were found
``edge_clipped``            most of the polygon lies outside the point coverage;
                            expected at tile edges, resolved by the tile buffer
``no_returns``              no returns of any class — a void in the LiDAR
``below_height_threshold``  returns exist but none reach recover.min_height_above_dtm,
                            typically a low shed or garage
``absent_building``         returns exist and are predominantly ground-classified:
                            the cadastral record is stale, the building is gone
``no_roof_points``          tall returns exist but none survived filtering
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

from .dtm import DTM
from pipeline_common.qa_record import StageRecord


def diagnose_footprints(
    gdf: gpd.GeoDataFrame,
    xyz: np.ndarray,
    classification: np.ndarray,
    roof_mask: np.ndarray,
    dtm: DTM,
    data_extent,
    min_height_above_dtm: float,
    ground_classes: tuple[int, ...] = (2, 11),
    min_coverage: float = 0.5,
    record: StageRecord | None = None,
) -> gpd.GeoDataFrame:
    """Classify why each footprint did or did not receive roof points."""
    x, y = xyz[:, 0], xyz[:, 1]
    hag = xyz[:, 2] - dtm.sample(x, y)
    is_ground = np.isin(classification, ground_classes)

    rows = []
    for i, geom in enumerate(gdf.geometry.values):
        bid = int(gdf["bid"].iloc[i])
        coverage = (geom.intersection(data_extent).area / geom.area) if geom.area else 0.0

        inside = shapely.contains_xy(geom, x, y)
        n_points = int(inside.sum())
        n_roof = int((inside & roof_mask).sum())
        n_ground = int((inside & is_ground).sum())
        max_hag = float(hag[inside].max()) if n_points else float("nan")

        if n_roof > 0:
            reason = "ok"
        elif coverage < min_coverage:
            reason = "edge_clipped"
        elif n_points == 0:
            reason = "no_returns"
        elif not np.isfinite(max_hag) or max_hag < min_height_above_dtm:
            reason = "below_height_threshold"
        elif n_ground / max(n_points, 1) > 0.5:
            reason = "absent_building"
        else:
            reason = "no_roof_points"

        rows.append({
            "bid": bid,
            "reason": reason,
            "coverage_in_data": round(coverage, 3),
            "n_points": n_points,
            "n_roof_points": n_roof,
            "n_ground_points": n_ground,
            "max_height_above_dtm": (round(max_hag, 2) if np.isfinite(max_hag) else None),
            "area_m2": round(float(geom.area), 1),
            "object_type": gdf.iloc[i].get("object_type_en"),
        })

    table = gpd.GeoDataFrame(rows, geometry=gdf.geometry.values, crs=gdf.crs)

    if record is not None:
        counts = table["reason"].value_counts().to_dict()
        record.count_in(footprints=len(gdf))
        record.count_out(**{f"reason_{k}": int(v) for k, v in counts.items()})

        ok = table[table["reason"] == "ok"]
        record.metric(
            reconstructable=int(len(ok)),
            reconstructable_pct=(round(100.0 * len(ok) / len(table), 2) if len(table) else None),
            median_roof_points_per_building=(
                int(ok["n_roof_points"].median()) if len(ok) else None),
            min_roof_points_per_building=(
                int(ok["n_roof_points"].min()) if len(ok) else None),
        )
        # Edge-clipped footprints are expected and resolved by the tile buffer,
        # so they are recorded but not raised as failures.
        for row in rows:
            if row["reason"] not in ("ok", "edge_clipped"):
                record.failure(
                    row["reason"], bid=row["bid"], area_m2=row["area_m2"],
                    object_type=row["object_type"],
                    max_height_above_dtm=row["max_height_above_dtm"],
                )
    return table
