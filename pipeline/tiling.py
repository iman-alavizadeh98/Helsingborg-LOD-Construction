"""1.5 Tiling.

Point cloud and footprints are tiled on one common grid. Each tile has a core
extent and a buffered extent; the buffer is what makes a building that straddles
a tile edge complete in every tile that touches it.

Ownership is decided by footprint centroid: a building is *owned* by exactly one
tile but may be *present* in several. Phase 4's merge step deduplicates on that
rule, so it is fixed here rather than left to the merge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import Polygon

from .qa_record import StageRecord

Bounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class TileSpec:
    """One cell of the tiling grid."""

    id: str
    col: int
    row: int
    core: Bounds       # exclusive upper edge; tiles partition the plane
    buffered: Bounds

    def core_polygon(self) -> Polygon:
        return Polygon.from_bounds(*self.core)

    def buffered_polygon(self) -> Polygon:
        return Polygon.from_bounds(*self.buffered)


def build_grid(extent: Bounds, cfg: dict) -> list[TileSpec]:
    """Cover `extent` with tiles on a grid anchored to an absolute origin."""
    size = float(cfg.get("size", 250.0))
    buffer = float(cfg.get("buffer", 20.0))
    origin = cfg.get("origin")

    minx, miny, maxx, maxy = extent
    if origin is None:
        # Anchor to absolute multiples of the tile size so that separately
        # processed areas share one grid.
        ox = math.floor(minx / size) * size
        oy = math.floor(miny / size) * size
    else:
        ox, oy = float(origin[0]), float(origin[1])

    ncols = max(1, math.ceil((maxx - ox) / size))
    nrows = max(1, math.ceil((maxy - oy) / size))

    tiles: list[TileSpec] = []
    for r in range(nrows):
        for c in range(ncols):
            x0, y0 = ox + c * size, oy + r * size
            core = (x0, y0, x0 + size, y0 + size)
            tiles.append(TileSpec(
                id=f"{c:03d}_{r:03d}", col=c, row=r, core=core,
                buffered=(x0 - buffer, y0 - buffer,
                          x0 + size + buffer, y0 + size + buffer),
            ))
    return tiles


def points_in_bounds(xy: np.ndarray, bounds: Bounds) -> np.ndarray:
    """Boolean mask of points inside a bounding box (upper edge exclusive)."""
    minx, miny, maxx, maxy = bounds
    x, y = xy[:, 0], xy[:, 1]
    return (x >= minx) & (x < maxx) & (y >= miny) & (y < maxy)


def assign_footprints(
    gdf: gpd.GeoDataFrame,
    tile: TileSpec,
    record: StageRecord | None = None,
) -> gpd.GeoDataFrame:
    """Footprints present in a tile, flagged with whether the tile owns them.

    ``present`` = intersects the buffered extent (needs reconstructing here for
    context). ``owned`` = centroid falls in the core extent (counts exactly once
    in the merged output).
    """
    buffered = tile.buffered_polygon()
    idx = gdf.sindex.query(buffered, predicate="intersects")
    present = gdf.iloc[np.sort(idx)].copy()

    if len(present) == 0:
        present["tile_id"] = []
        present["owned"] = []
        return present

    centroids = shapely.centroid(present.geometry.values)
    cx = shapely.get_x(centroids)
    cy = shapely.get_y(centroids)
    minx, miny, maxx, maxy = tile.core
    present["tile_id"] = tile.id
    present["owned"] = (cx >= minx) & (cx < maxx) & (cy >= miny) & (cy < maxy)

    if record is not None:
        record.count_in(footprints_total=len(gdf))
        record.count_out(
            footprints_present=len(present),
            footprints_owned=int(present["owned"].sum()),
            footprints_context_only=int((~present["owned"]).sum()),
        )
    return present


def tile_for_extent(extent: Bounds, tile_id: str, cfg: dict) -> TileSpec:
    """A single TileSpec covering `extent`, keeping the configured buffer.

    Used when a LAS file is already a delivered tile: the file's own extent is
    the core, so it is not re-cut, but the buffer still applies when pulling in
    neighbouring footprints.
    """
    buffer = float(cfg.get("buffer", 20.0))
    minx, miny, maxx, maxy = extent
    return TileSpec(
        id=tile_id, col=0, row=0,
        core=(minx, miny, maxx, maxy),
        buffered=(minx - buffer, miny - buffer, maxx + buffer, maxy + buffer),
    )
