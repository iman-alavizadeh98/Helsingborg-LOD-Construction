"""1.1 Ground and DTM.

Rasterise ground returns to a regular grid, then fill the holes left under
buildings by exact nearest-valid-cell.

Height above ground is later read straight out of this raster
(``DTM.sample``) rather than by a per-building spatial query over the ground
points — the plan calls that out as orders of magnitude slower.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy import ndimage

from .qa_record import StageRecord

NODATA = -9999.0


@dataclass
class DTM:
    """A rasterised terrain model in the project CRS."""

    grid: np.ndarray        # (rows, cols) float64, NaN where still unknown
    transform: rasterio.Affine
    crs: str
    resolution: float
    observed: np.ndarray    # (rows, cols) bool, True where a ground return landed

    @property
    def shape(self) -> tuple[int, int]:
        return self.grid.shape

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Nearest-cell lookup of terrain height at real-world coordinates.

        Nearest-cell rather than bilinear: at 0.5 m the difference is far below
        the 2 m height-above-ground threshold it feeds, and it cannot smear
        values across the edge of a filled hole.
        """
        rows, cols = self.grid.shape
        inv = ~self.transform
        # Affine maps cell corners; the 0.5 offset lands us on cell centres.
        fc, fr = inv * (np.asarray(x, dtype=np.float64),
                        np.asarray(y, dtype=np.float64))
        c = np.clip(np.floor(fc).astype(np.int64), 0, cols - 1)
        r = np.clip(np.floor(fr).astype(np.int64), 0, rows - 1)
        return self.grid[r, c]

    def write(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = np.where(np.isfinite(self.grid), self.grid, NODATA).astype("float32")
        with rasterio.open(
            path, "w", driver="GTiff",
            height=out.shape[0], width=out.shape[1], count=1,
            dtype="float32", crs=self.crs, transform=self.transform,
            nodata=NODATA, compress="deflate", tiled=True,
        ) as dst:
            dst.write(out, 1)
        return path


def _cell_indices(
    x: np.ndarray, y: np.ndarray,
    minx: float, maxy: float, res: float,
    nrows: int, ncols: int,
) -> tuple[np.ndarray, np.ndarray]:
    col = np.floor((x - minx) / res).astype(np.int64)
    row = np.floor((maxy - y) / res).astype(np.int64)
    np.clip(col, 0, ncols - 1, out=col)
    np.clip(row, 0, nrows - 1, out=row)
    return row, col


def _reduce_per_cell(
    flat: np.ndarray, z: np.ndarray, ncells: int, statistic: str
) -> np.ndarray:
    """Reduce point heights to one value per occupied cell."""
    grid = np.full(ncells, np.nan, dtype=np.float64)
    if flat.size == 0:
        return grid

    if statistic == "min":
        np.fmin.at(grid, flat, z)
        return grid
    if statistic == "mean":
        total = np.zeros(ncells, dtype=np.float64)
        count = np.zeros(ncells, dtype=np.int64)
        np.add.at(total, flat, z)
        np.add.at(count, flat, 1)
        occupied = count > 0
        grid[occupied] = total[occupied] / count[occupied]
        return grid
    if statistic != "median":
        raise ValueError(f"unknown dtm.cell_statistic '{statistic}'")

    # Median: sort by (cell, z) then pick the middle element of each run.
    order = np.lexsort((z, flat))
    fs, zs = flat[order], z[order]
    cells, starts, counts = np.unique(fs, return_index=True, return_counts=True)
    grid[cells] = zs[starts + counts // 2]
    return grid


def build_dtm(
    xyz: np.ndarray,
    classification: np.ndarray,
    crs: str,
    cfg: dict,
    bounds: tuple[float, float, float, float] | None = None,
    record: StageRecord | None = None,
) -> DTM:
    """Build a gap-filled DTM from the ground-classified returns."""
    res = float(cfg.get("resolution", 0.5))
    ground_classes = list(cfg.get("ground_classes", [2]))
    statistic = str(cfg.get("cell_statistic", "median"))

    mask = np.isin(classification, ground_classes)
    gx, gy, gz = xyz[mask, 0], xyz[mask, 1], xyz[mask, 2]

    if gz.size == 0:
        raise ValueError(
            f"no points in ground classes {ground_classes}; cannot build a DTM"
        )

    if bounds is None:
        bounds = (xyz[:, 0].min(), xyz[:, 1].min(), xyz[:, 0].max(), xyz[:, 1].max())
    minx, miny, maxx, maxy = bounds

    # Snap the grid to absolute multiples of the resolution so that tiles
    # processed separately share one grid and their DTMs line up exactly.
    minx = math.floor(minx / res) * res
    miny = math.floor(miny / res) * res
    maxx = math.ceil(maxx / res) * res
    maxy = math.ceil(maxy / res) * res

    ncols = max(1, int(round((maxx - minx) / res)))
    nrows = max(1, int(round((maxy - miny) / res)))

    row, col = _cell_indices(gx, gy, minx, maxy, res, nrows, ncols)
    flat = row * ncols + col
    grid = _reduce_per_cell(flat, gz, nrows * ncols, statistic).reshape(nrows, ncols)

    observed = np.isfinite(grid)
    n_observed = int(observed.sum())
    n_cells = nrows * ncols

    filled_count = 0
    unfilled_count = 0
    if cfg.get("fill_gaps", True) and n_observed and n_observed < n_cells:
        # EDT measures distance to the nearest zero; feed it the *gap* mask so
        # the returned indices point at the nearest observed cell.
        gaps = ~observed
        distance, (nr, nc) = ndimage.distance_transform_edt(
            gaps, sampling=(res, res), return_indices=True
        )
        max_dist = float(cfg.get("max_fill_distance", 0.0) or 0.0)
        fillable = gaps
        if max_dist > 0:
            fillable = gaps & (distance <= max_dist)
        grid[fillable] = grid[nr[fillable], nc[fillable]]
        filled_count = int(fillable.sum())
        unfilled_count = int((gaps & ~fillable).sum())

    dtm = DTM(grid=grid, transform=from_origin(minx, maxy, res, res),
              crs=crs, resolution=res, observed=observed)

    if record is not None:
        finite = grid[np.isfinite(grid)]
        record.count_in(ground_points=int(gz.size), ground_classes=ground_classes)
        record.count_out(
            grid_rows=nrows, grid_cols=ncols, cells_total=n_cells,
            cells_observed=n_observed, cells_filled=filled_count,
            cells_nodata=unfilled_count,
        )
        record.metric(
            resolution_m=res, cell_statistic=statistic,
            coverage_observed_pct=round(100.0 * n_observed / n_cells, 2),
            z_min=float(finite.min()) if finite.size else None,
            z_max=float(finite.max()) if finite.size else None,
            z_median=float(np.median(finite)) if finite.size else None,
        )
        if unfilled_count:
            record.failure(
                "dtm_nodata_cells", count=unfilled_count,
                note="beyond dtm.max_fill_distance from any ground return",
            )
    return dtm
