"""Loading LAS point clouds and cadastral footprints.

CRS hygiene (plan 1.4): coordinates are kept in real-world EPSG:3008 the whole
way through. Nothing is translated to a local frame. Where a computation needs
numerical conditioning (volumes, PCA), the recentring is local to that
computation and never written back to a GeoDataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import laspy
import numpy as np
from shapely.geometry import Polygon


@dataclass
class PointCloud:
    """Point coordinates in EPSG:3008 plus the per-point attributes we use."""

    xyz: np.ndarray            # (N, 3) float64, real-world coordinates
    classification: np.ndarray  # (N,) uint8
    return_number: np.ndarray   # (N,) uint8
    number_of_returns: np.ndarray  # (N,) uint8
    crs: str
    source: Path

    def __len__(self) -> int:
        return int(self.xyz.shape[0])

    @property
    def x(self) -> np.ndarray:
        return self.xyz[:, 0]

    @property
    def y(self) -> np.ndarray:
        return self.xyz[:, 1]

    @property
    def z(self) -> np.ndarray:
        return self.xyz[:, 2]

    def bounds(self) -> tuple[float, float, float, float]:
        return (
            float(self.x.min()), float(self.y.min()),
            float(self.x.max()), float(self.y.max()),
        )

    def class_counts(self) -> dict[int, int]:
        codes, counts = np.unique(self.classification, return_counts=True)
        return {int(c): int(n) for c, n in zip(codes, counts)}

    def subset(self, mask: np.ndarray) -> "PointCloud":
        return PointCloud(
            xyz=self.xyz[mask],
            classification=self.classification[mask],
            return_number=self.return_number[mask],
            number_of_returns=self.number_of_returns[mask],
            crs=self.crs,
            source=self.source,
        )


def read_las(path: Path | str, expected_crs: str | None = None) -> PointCloud:
    """Read a LAS/LAZ file into real-world float64 coordinates."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"LAS file not found: {path}")

    las = laspy.read(str(path))

    # laspy's .x/.y/.z apply scale and offset and return float64.
    xyz = np.column_stack(
        (np.asarray(las.x, dtype=np.float64),
         np.asarray(las.y, dtype=np.float64),
         np.asarray(las.z, dtype=np.float64))
    )

    file_crs = None
    try:
        parsed = las.header.parse_crs()
        if parsed is not None:
            file_crs = f"EPSG:{parsed.to_epsg()}" if parsed.to_epsg() else parsed.to_string()
    except Exception:
        file_crs = None

    crs = file_crs or expected_crs
    if expected_crs and file_crs and file_crs != expected_crs:
        raise ValueError(
            f"{path.name} declares {file_crs} but the project CRS is "
            f"{expected_crs}; reproject the tile rather than relabelling it"
        )

    def _dim(name: str) -> np.ndarray:
        if name in las.point_format.dimension_names:
            return np.asarray(getattr(las, name), dtype=np.uint8)
        return np.zeros(xyz.shape[0], dtype=np.uint8)

    return PointCloud(
        xyz=xyz,
        classification=np.asarray(las.classification, dtype=np.uint8),
        return_number=_dim("return_number"),
        number_of_returns=_dim("number_of_returns"),
        crs=crs or "unknown",
        source=path,
    )


def read_footprints(
    path: Path | str,
    layer: str | None,
    target_crs: str,
    source_crs: str | None = None,
    explode: bool = True,
    min_area: float = 0.0,
) -> gpd.GeoDataFrame:
    """Load cadastral footprints, reproject to the project CRS, explode to
    single-part Polygons.

    Returns a GeoDataFrame whose ``crs`` genuinely matches its coordinates —
    the prototype's latent bug was tagging translated coordinates as 3008.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"footprint file not found: {path}")

    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)

    if gdf.crs is None:
        if source_crs is None:
            raise ValueError(
                f"{path.name} has no CRS and paths.footprints_crs is not set"
            )
        gdf = gdf.set_crs(source_crs)

    if str(gdf.crs) != str(target_crs):
        gdf = gdf.to_crs(target_crs)

    if explode:
        gdf = gdf.explode(index_parts=False, ignore_index=True)

    # Drop anything that is not a Polygon (explode can leave stray types).
    gdf = gdf[gdf.geom_type == "Polygon"].copy()

    # make_valid before any area test so self-touching rings do not vanish.
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].make_valid()
        gdf = gdf[gdf.geom_type == "Polygon"].copy()

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    if min_area > 0:
        gdf = gdf[gdf.geometry.area >= min_area].copy()

    gdf = gdf.reset_index(drop=True)
    # Stable per-part identifier; object_id is not unique after exploding.
    # Deliberately not called "fid": that is GeoPackage's reserved primary-key
    # column, and a column of that name is swallowed on write.
    gdf["bid"] = np.arange(len(gdf), dtype=np.int64)
    return gdf


def clip_footprints(
    gdf: gpd.GeoDataFrame,
    bounds: tuple[float, float, float, float],
    buffer: float = 0.0,
) -> gpd.GeoDataFrame:
    """Footprints intersecting a bounding box, optionally grown by `buffer`."""
    minx, miny, maxx, maxy = bounds
    box = Polygon.from_bounds(
        minx - buffer, miny - buffer, maxx + buffer, maxy + buffer
    )
    idx = gdf.sindex.query(box, predicate="intersects")
    return gdf.iloc[np.sort(idx)].copy()
