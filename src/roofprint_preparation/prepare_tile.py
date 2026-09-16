# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""Phase 1 driver — prepare one tile for reconstruction.

    python main.py prepare --tile 6204_105

Runs 1.1 through 1.5 and writes, into ``out/work/<tile>/``:

* ``<tile>_dtm.tif``        — gap-filled terrain raster
* ``<tile>_prepared.las``   — ground (class 2) + roof candidates (class 6)
* ``<tile>_roofprints.gpkg``— footprints buffered by the calibrated offset

plus a QA record per stage in ``out/qa/``.

The prepared LAS relabels every recovered roof point to class 6. Roofer may
select building points by classification; if it does, an unrelabelled cloud
would silently drop the class-12 returns that this phase exists to recover.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import laspy
import numpy as np
import pyproj
from shapely.geometry import Polygon

from pipeline_common.config import Config, load_config
from .footprint_diagnosis import diagnose_footprints
from .dtm import build_dtm
from .roofprint_offset import measure_offset, recommend_buffer, sweep_buffer
from .readers import clip_footprints, read_footprints, read_las
from pipeline_common.qa_record import TileQA
from .overlap_recovery import recover_roof_points
from .tiling import assign_footprints, tile_for_extent


def write_prepared_las(
    path: Path,
    source_header: laspy.LasHeader,
    xyz: np.ndarray,
    classification: np.ndarray,
    crs: str,
) -> Path:
    """Write a cloud with roof candidates relabelled to class 6."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = laspy.LasHeader(
        version=source_header.version, point_format=source_header.point_format
    )
    # Reuse the source scales and offsets so the quantisation grid is identical
    # and no coordinate is re-rounded on the way out.
    header.scales = source_header.scales
    header.offsets = source_header.offsets
    header.add_crs(pyproj.CRS.from_user_input(crs))

    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    las.classification = classification
    las.write(str(path))
    return path


def prepare_tile(cfg: Config, tile_id: str) -> dict:
    tile = cfg.tile(tile_id)
    work = cfg.tile_dir(tile_id)
    qa = TileQA(tile_id, cfg.qa_dir, config=cfg.as_dict())

    # -- load ---------------------------------------------------------------
    rec = qa.stage("0-load")
    cloud = read_las(tile.las, expected_crs=cfg.crs)
    class_counts = cloud.class_counts()
    extent = cloud.bounds()
    area = (extent[2] - extent[0]) * (extent[3] - extent[1])
    rec.count_in(las_file=tile.las.name)
    rec.count_out(points=len(cloud), **{f"class_{k}": v for k, v in class_counts.items()})
    rec.metric(
        crs=cloud.crs, extent=[round(v, 2) for v in extent],
        extent_x_m=round(extent[2] - extent[0], 1),
        extent_y_m=round(extent[3] - extent[1], 1),
        density_pts_per_m2=round(len(cloud) / area, 2) if area else None,
    )
    rec.finish()

    # -- 1.5 tile geometry --------------------------------------------------
    rec = qa.stage("1.5-tiling")
    spec = tile_for_extent(extent, tile_id, cfg.section("tiling"))
    rec.count_out(core=[round(v, 2) for v in spec.core],
                  buffered=[round(v, 2) for v in spec.buffered])
    rec.metric(buffer_m=cfg.section("tiling").get("buffer"))
    rec.finish()

    # -- 1.1 DTM ------------------------------------------------------------
    rec = qa.stage("1.1-dtm")
    dtm = build_dtm(cloud.xyz, cloud.classification, cfg.crs,
                    cfg.section("dtm"), bounds=extent, record=rec)
    dtm_path = dtm.write(work / f"{tile_id}_dtm.tif")
    rec.output(dtm_path)
    rec.finish()

    # -- 1.2 recover --------------------------------------------------------
    rec = qa.stage("1.2-recover")
    roof_mask, details = recover_roof_points(
        cloud.xyz, cloud.classification, dtm, cfg.section("recover"), record=rec
    )
    rec.finish()
    roof_xyz = cloud.xyz[roof_mask]

    # -- 1.3 footprints -----------------------------------------------------
    rec = qa.stage("1.3-footprints")
    fcfg = cfg.section("footprints")
    all_footprints = read_footprints(
        cfg.footprints_path, cfg.footprints_layer, target_crs=cfg.crs,
        source_crs=cfg.footprints_crs, explode=bool(fcfg.get("explode", True)),
        min_area=float(fcfg.get("min_area", 0.0)),
    )
    footprints = clip_footprints(all_footprints, spec.core,
                                 buffer=float(cfg.section("tiling").get("buffer", 0.0)))
    rec.count_in(footprints_total=len(all_footprints))
    rec.count_out(footprints_in_tile=len(footprints))
    rec.finish()

    rec = qa.stage("1.3-offset")
    median_offset, table = measure_offset(
        footprints, roof_xyz[:, :2], fcfg, record=rec,
        data_extent=Polygon.from_bounds(*spec.core),
    )
    rec.finish()

    rec = qa.stage("1.4-diagnose")
    diagnosis = diagnose_footprints(
        footprints, cloud.xyz, cloud.classification, roof_mask, dtm,
        data_extent=Polygon.from_bounds(*spec.core),
        min_height_above_dtm=float(cfg.section("recover").get("min_height_above_dtm", 2.0)),
        ground_classes=tuple(cfg.section("dtm").get("ground_classes", [2])) + (11,),
        record=rec,
    )
    rec.finish()

    rec = qa.stage("1.3-buffer-sweep")
    other_xyz = cloud.xyz[~roof_mask]
    sweep = sweep_buffer(footprints, roof_xyz[:, :2], other_xyz[:, :2], fcfg, record=rec)
    configured = fcfg.get("buffer")
    chosen = float(configured) if configured is not None else recommend_buffer(sweep)
    rec.metric(
        measured_median_offset_m=(round(median_offset, 3) if median_offset else None),
        chosen_buffer_m=chosen,
        buffer_source="config" if configured is not None else "sweep recommendation",
    )
    rec.finish()

    # -- outputs ------------------------------------------------------------
    rec = qa.stage("1-outputs")

    ground_classes = list(cfg.section("dtm").get("ground_classes", [2]))
    ground_mask = np.isin(cloud.classification, ground_classes) & ~roof_mask
    keep = roof_mask | ground_mask
    out_class = np.where(roof_mask[keep], 6, 2).astype(np.uint8)

    source_header = laspy.read(str(tile.las)).header
    las_path = write_prepared_las(
        work / f"{tile_id}_prepared.las", source_header,
        cloud.xyz[keep], out_class, cfg.crs,
    )

    # Only footprints this tile *owns* (centroid in the core extent) are handed
    # to roofer. The tile buffer exists to complete the point cloud around an
    # edge building, not to reconstruct the neighbour's buildings: passing the
    # ring footprints too would emit them as empty "no points" buildings here
    # and again, properly, from the tile that owns them.
    owned = assign_footprints(footprints, spec)
    roofprints = owned[owned["owned"]].copy() if len(owned) else owned
    if chosen > 0 and len(roofprints):
        roofprints["geometry"] = roofprints.geometry.buffer(chosen, join_style="mitre")
    gpkg_path = work / f"{tile_id}_roofprints.gpkg"
    roofprints.to_file(gpkg_path, layer="roofprints", driver="GPKG")

    table_path = cfg.qa_dir / f"{tile_id}_per_building.csv"
    per_building = (
        diagnosis.drop(columns="geometry")
        .merge(table.drop(columns="geometry"), on="bid", how="outer")
    )
    per_building.to_csv(table_path, index=False)

    rec.count_out(
        prepared_points=int(keep.sum()),
        roof_points_class6=int(roof_mask.sum()),
        ground_points_class2=int(ground_mask.sum()),
        footprints_considered=len(footprints),
        roofprints_owned=len(roofprints),
        roofprints_context_only_dropped=len(footprints) - len(roofprints),
    )
    rec.output(las_path).output(gpkg_path).output(table_path)
    rec.finish()

    json_path, md_path = qa.write()
    return {
        "tile": tile_id,
        "qa_json": json_path,
        "qa_md": md_path,
        "las": las_path,
        "gpkg": gpkg_path,
        "dtm": dtm_path,
        "median_offset_m": median_offset,
        "chosen_buffer_m": chosen,
        "roof_points": int(roof_mask.sum()),
        "details": details,
        "sweep": sweep,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prepare one tile (Phase 1).")
    ap.add_argument("--tile", help="tile id from config.yml; default: all tiles")
    ap.add_argument("--config", default=None, help="path to config.yml")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    tile_ids = [args.tile] if args.tile else [t.id for t in cfg.tiles()]
    if not tile_ids:
        print("no tiles configured", file=sys.stderr)
        return 2

    for tile_id in tile_ids:
        result = prepare_tile(cfg, tile_id)
        print(f"\n=== tile {tile_id} ===")
        print(f"  roof points      : {result['roof_points']:,}")
        print(f"  measured offset  : {result['median_offset_m']}")
        print(f"  chosen buffer    : {result['chosen_buffer_m']} m")
        print(f"  QA report        : {result['qa_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
