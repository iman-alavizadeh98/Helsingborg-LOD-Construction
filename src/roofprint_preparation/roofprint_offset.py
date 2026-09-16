# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""1.3 Measure the footprint/roofprint offset, and sweep the buffer.

Cadastral polygons are ground footprints collected at the facade
(``collection_level = "Fasad"``); roofer wants the roof outline, which sits
outside them by the eave overhang. The offset is measured from the data rather
than guessed: for each building, the median distance from roof points lying
*outside* its polygon to that polygon's boundary.

The buffer sweep then reports two competing quantities per candidate distance:

* **capture rate** — the share of roof points that fall inside a buffered
  footprint. Rises with the buffer.
* **annulus purity** — of the points newly admitted by the buffer, the share
  that are roof candidates rather than ground or vegetation. Falls with the
  buffer once the eave is cleared.

The right buffer is the largest one that still buys capture without spending
purity; both numbers go in the QA report so the choice is visible.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely
from shapely.strtree import STRtree

from pipeline_common.qa_record import StageRecord


def _point_geoms(x: np.ndarray, y: np.ndarray):
    return shapely.points(np.asarray(x, dtype=np.float64),
                          np.asarray(y, dtype=np.float64))


def measure_offset(
    gdf: gpd.GeoDataFrame,
    roof_xy: np.ndarray,
    cfg: dict,
    record: StageRecord | None = None,
    data_extent=None,
) -> tuple[float | None, gpd.GeoDataFrame]:
    """Estimate the systematic footprint -> roofprint offset.

    Returns the median per-building offset and a per-building table.

    ``data_extent`` is the region actually covered by points. Footprints pulled
    in from the tile's buffer ring fall outside it and are *expected* to have no
    points, so they are marked context-only rather than reported as failures.
    """
    search = float(cfg.get("offset_search_distance", 3.0))
    min_pts = int(cfg.get("min_points_for_offset", 20))

    x, y = roof_xy[:, 0], roof_xy[:, 1]
    pts = _point_geoms(x, y)
    tree = STRtree(pts)

    geoms = gdf.geometry.values
    # A point inside *any* footprint belongs to that building's roof, so it
    # must not be counted as another building's overhang.
    inside_any = np.zeros(pts.shape[0], dtype=bool)
    for geom in geoms:
        hit = tree.query(geom, predicate="contains")
        inside_any[hit] = True

    rows = []
    for i, geom in enumerate(geoms):
        bid = int(gdf["bid"].iloc[i])
        near = tree.query(shapely.buffer(geom, search, join_style="mitre"),
                          predicate="intersects")
        if near.size == 0:
            rows.append({"bid": bid, "n_inside": 0, "n_outside": 0,
                         "offset_m": np.nan})
            continue

        inside_mask = shapely.contains_xy(geom, x[near], y[near])
        n_inside = int(inside_mask.sum())

        # Overhang candidates: near this footprint, outside it, and not
        # claimed by a neighbouring footprint.
        cand = near[~inside_mask & ~inside_any[near]]
        if cand.size:
            dist = shapely.distance(pts[cand], geom.exterior)
            offset = float(np.median(dist)) if cand.size >= min_pts else np.nan
        else:
            offset = np.nan

        rows.append({"bid": bid, "n_inside": n_inside,
                     "n_outside": int(cand.size), "offset_m": offset})

    table = gpd.GeoDataFrame(rows, geometry=gdf.geometry.values, crs=gdf.crs)

    if data_extent is not None:
        table["in_data_extent"] = shapely.intersects(gdf.geometry.values, data_extent)
    else:
        table["in_data_extent"] = True

    valid = table["offset_m"].to_numpy(dtype=float)
    valid = valid[np.isfinite(valid)]
    median_offset = float(np.median(valid)) if valid.size else None

    empty = table["n_inside"] == 0
    empty_in_data = empty & table["in_data_extent"]

    if record is not None:
        record.count_in(footprints=len(gdf), roof_points=int(pts.shape[0]))
        record.count_out(
            footprints_in_data_extent=int(table["in_data_extent"].sum()),
            footprints_context_only=int((~table["in_data_extent"]).sum()),
            footprints_with_offset=int(valid.size),
            footprints_without_points=int(empty_in_data.sum()),
        )
        record.metric(
            median_offset_m=(round(median_offset, 3) if median_offset else None),
            offset_p25_m=(round(float(np.percentile(valid, 25)), 3) if valid.size else None),
            offset_p75_m=(round(float(np.percentile(valid, 75)), 3) if valid.size else None),
            offset_search_distance_m=search,
        )
        for row, flag in zip(rows, empty_in_data.to_numpy()):
            if flag:
                record.failure("footprint_without_points", bid=row["bid"])
    return median_offset, table


def sweep_buffer(
    gdf: gpd.GeoDataFrame,
    roof_xy: np.ndarray,
    other_xy: np.ndarray,
    cfg: dict,
    record: StageRecord | None = None,
) -> list[dict]:
    """Evaluate each candidate buffer by capture rate and annulus purity.

    ``other_xy`` are the non-candidate points (ground, vegetation, noise) —
    what a too-large buffer starts sweeping up.
    """
    sweep = [float(b) for b in cfg.get("buffer_sweep", [0.0, 0.25, 0.5, 0.75, 1.0])]
    geoms = gdf.geometry.values

    roof_pts = _point_geoms(roof_xy[:, 0], roof_xy[:, 1])
    other_pts = _point_geoms(other_xy[:, 0], other_xy[:, 1])
    roof_tree = STRtree(roof_pts)
    other_tree = STRtree(other_pts)
    n_roof = int(roof_pts.shape[0])

    def captured(tree, buffer: float) -> np.ndarray:
        hit = np.zeros(tree.geometries.shape[0], dtype=bool)
        for geom in geoms:
            g = shapely.buffer(geom, buffer, join_style="mitre") if buffer > 0 else geom
            hit[tree.query(g, predicate="intersects")] = True
        return hit

    base_roof = captured(roof_tree, 0.0)
    base_other = captured(other_tree, 0.0)

    results = []
    for buffer in sweep:
        roof_hit = base_roof if buffer == 0 else captured(roof_tree, buffer)
        other_hit = base_other if buffer == 0 else captured(other_tree, buffer)

        # Points newly admitted by this buffer, relative to no buffer.
        new_roof = int((roof_hit & ~base_roof).sum())
        new_other = int((other_hit & ~base_other).sum())
        new_total = new_roof + new_other

        results.append({
            "buffer_m": buffer,
            "roof_points_captured": int(roof_hit.sum()),
            "capture_rate_pct": round(100.0 * roof_hit.sum() / n_roof, 2) if n_roof else None,
            "new_roof_points": new_roof,
            "new_other_points": new_other,
            "annulus_purity_pct": (round(100.0 * new_roof / new_total, 2)
                                   if new_total else None),
        })

    if record is not None:
        record.count_in(footprints=len(gdf), roof_points=n_roof,
                        other_points=int(other_pts.shape[0]))
        record.metric(sweep=results)
    return results


def recommend_buffer(sweep: list[dict], min_purity_pct: float = 50.0) -> float:
    """Largest swept buffer whose newly admitted points are still mostly roof.

    Purity is undefined at buffer 0 (nothing is newly admitted); that entry is
    the fallback if no buffer clears the bar.
    """
    best = 0.0
    for row in sweep:
        purity = row.get("annulus_purity_pct")
        if row["buffer_m"] == 0.0 or purity is None:
            continue
        if purity >= min_purity_pct:
            best = max(best, row["buffer_m"])
    return best
