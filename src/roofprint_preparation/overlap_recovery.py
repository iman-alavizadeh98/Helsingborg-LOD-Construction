# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""1.2 Recover the overlap class.

Class 12 (flight-strip overlap) is 38% of this data and carries most of the
roof returns; class 1 is unclassified. Neither is labelled as building, so
selecting on ``classification == 6`` throws most of the roof away.

Candidates are therefore chosen geometrically — height above the DTM — and
residual vegetation is removed by local surface planarity rather than by class
label, since the classes we are recovering carry no reliable label to filter on.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .dtm import DTM
from pipeline_common.qa_record import StageRecord


def surface_variation(
    xyz: np.ndarray,
    k: int = 12,
    max_radius: float = 1.5,
    chunk: int = 100_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Local surface variation from PCA over each point's k nearest neighbours.

    Returns ``(variation, valid)``. Variation is l0 / (l0 + l1 + l2) over the
    neighbourhood covariance eigenvalues: ~0 on a locally planar surface such
    as a roof, and rising towards 1/3 on scattered returns such as foliage.

    Coordinates are recentred per chunk before the covariance is formed. At
    x~3.6e5, y~6.2e6 the squared terms would otherwise lose the precision the
    small eigenvalue depends on.
    """
    n = xyz.shape[0]
    variation = np.full(n, np.nan, dtype=np.float64)
    valid = np.zeros(n, dtype=bool)
    if n == 0:
        return variation, valid

    tree = cKDTree(xyz)
    k_eff = min(k + 1, n)  # +1: the query point is its own nearest neighbour

    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        block = xyz[start:stop]

        dist, idx = tree.query(
            block, k=k_eff,
            distance_upper_bound=max_radius if max_radius > 0 else np.inf,
            workers=-1,
        )
        if idx.ndim == 1:
            dist, idx = dist[:, None], idx[:, None]

        # Points beyond the radius come back as index == n with dist == inf.
        good = np.isfinite(dist) & (idx < n)
        counts = good.sum(axis=1)
        enough = counts >= 4
        if not enough.any():
            continue

        safe_idx = np.where(good, idx, 0)
        neigh = xyz[safe_idx]                       # (m, k_eff, 3)
        w = good[..., None].astype(np.float64)      # mask out padding
        nvalid = counts[:, None, None].astype(np.float64)

        centroid = (neigh * w).sum(axis=1, keepdims=True) / np.maximum(nvalid, 1.0)
        centred = (neigh - centroid) * w
        cov = np.einsum("nki,nkj->nij", centred, centred)
        cov /= np.maximum(counts[:, None, None] - 1, 1)

        eig = np.linalg.eigvalsh(cov[enough])       # ascending
        total = eig.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.where(total > 0, eig[:, 0] / total, np.nan)

        out = np.full(stop - start, np.nan)
        out[enough] = v
        variation[start:stop] = out
        valid[start:stop] = enough & np.isfinite(out)

    return variation, valid


def recover_roof_points(
    xyz: np.ndarray,
    classification: np.ndarray,
    dtm: DTM,
    cfg: dict,
    record: StageRecord | None = None,
) -> tuple[np.ndarray, dict]:
    """Select the candidate roof-point set.

    Returns a boolean mask over the input points plus a details dict.
    """
    building_classes = list(cfg.get("building_classes", [6]))
    recover_classes = list(cfg.get("recover_classes", [1, 12]))
    exclude_classes = list(cfg.get("exclude_classes", [7]))
    min_hag = float(cfg.get("min_height_above_dtm", 2.0))

    hag = xyz[:, 2] - dtm.sample(xyz[:, 0], xyz[:, 1])

    is_building = np.isin(classification, building_classes)
    is_recoverable = np.isin(classification, recover_classes)
    excluded = np.isin(classification, exclude_classes)

    baseline = is_building & ~excluded
    recovered = is_recoverable & ~excluded & np.isfinite(hag) & (hag > min_hag)
    candidates = baseline | recovered

    details: dict = {
        "baseline_points": int(baseline.sum()),
        "recovered_points": int(recovered.sum()),
        "candidates_before_planarity": int(candidates.sum()),
        "per_class_recovered": {
            int(c): int((recovered & (classification == c)).sum())
            for c in recover_classes
        },
    }

    pcfg = cfg.get("planarity", {}) or {}
    kept = candidates
    if pcfg.get("enabled", True) and candidates.any():
        idx = np.flatnonzero(candidates)
        variation, valid = surface_variation(
            xyz[idx],
            k=int(pcfg.get("k_neighbours", 12)),
            max_radius=float(pcfg.get("max_radius", 1.5)),
        )
        max_var = float(pcfg.get("max_surface_variation", 0.06))
        planar = valid & (variation <= max_var)

        kept = np.zeros_like(candidates)
        kept[idx[planar]] = True

        details["planarity"] = {
            "max_surface_variation": max_var,
            "rejected_non_planar": int((valid & ~planar).sum()),
            "rejected_too_few_neighbours": int((~valid).sum()),
            "median_variation": (
                float(np.nanmedian(variation[valid])) if valid.any() else None
            ),
            # Reported per source so the filter's effect on the already
            # building-classified points stays visible.
            "removed_from_class_6": int((baseline & ~kept).sum()),
            "removed_from_recovered": int((recovered & ~kept).sum()),
        }

    details["final_points"] = int(kept.sum())
    base_kept = int((baseline & kept).sum())
    details["gain_factor"] = (
        round(details["final_points"] / base_kept, 3) if base_kept else None
    )

    if record is not None:
        record.count_in(
            total_points=int(xyz.shape[0]),
            class_6_points=int(is_building.sum()),
            recoverable_class_points=int(is_recoverable.sum()),
        )
        record.count_out(
            baseline_class_6=details["baseline_points"],
            recovered_geometrically=details["recovered_points"],
            candidates_before_planarity=details["candidates_before_planarity"],
            final_roof_points=details["final_points"],
        )
        record.metric(
            min_height_above_dtm=min_hag,
            per_class_recovered=details["per_class_recovered"],
            gain_over_class6_only=details["gain_factor"],
            **({"planarity": details["planarity"]} if "planarity" in details else {}),
        )
        if details["final_points"] == 0:
            record.failure("no_roof_points", note="candidate set is empty")

    return kept, details
