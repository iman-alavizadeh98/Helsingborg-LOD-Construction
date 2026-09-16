# LOD2.2 Building Reconstruction — Helsingborg

Student research project, open source, GPL-3.0. Airborne LiDAR + cadastral
footprints → LOD2.2 building models as CityJSON.

Full specification: @PROJECT_PLAN.md — read it before starting new work.

## Standing rules

- **Do not write a reconstruction algorithm.** `roofer` is the engine. A
  from-scratch prototype was already built and evaluated; its output was too
  noisy to use. If reconstruction quality is the problem, tune roofer or
  compare against City3D — do not reimplement.
- **Do not port anything to C++ for accuracy.** Language affects speed, not
  geometric resolution. Both use float64.
- **Do not filter LiDAR on `classification == 6`.** Class 12 (overlap) is 38%
  of this data and holds most of the roof returns. Select geometrically:
  height above the DTM, not class label.
- **Never translate coordinates to a local frame.** roofer takes real-world
  coordinates. Do recentre before any volume computation — at 6.2e6 m the
  divergence-theorem sum loses all precision.
- **Do not modify the Python prototype in `qa/`.** It is the validation
  harness, not a deliverable.

## Project facts

- CRS: **EPSG:3008** (SWEREF99 13 30) everywhere. Footprints arrive as
  EPSG:3006 and must be reprojected and exploded to single-part Polygons.
- Point density ~50 pts/m². Roofer defaults are tuned for lower-density Dutch
  AHN data — expect to retune plane-detection thresholds.
- Footprints are ground outlines; roofer wants roofprints. Buffer outward by
  the calibrated offset (see PROJECT_PLAN §1.3) before use.
- Terraced rows are the known failure mode. Always use real cadastral
  footprints rather than outlines derived from the point cloud.

## Layout

```
data/          # LAS tiles, footprint GPKG (gitignored)
pipeline/      # tiling, DTM, point recovery, roofer invocation
qa/            # validation harness — RANSAC plane stats, metrics, val3dity
out/           # CityJSON, reports (gitignored)
```

## Commands

All stages are driven by `config.yml`; paths in it resolve against its own
directory, so these work from anywhere.

```bash
# prepare a tile (Phase 1: DTM, point recovery, offset calibration, outputs)
python -m pipeline.prepare_tile --tile 6204_105

# run roofer (Phase 2) — --dry-run writes the TOML and prints the command only
python -m pipeline.run_roofer --tile 6204_105

# inspect the result: LoDs, semantic surfaces, roof forms, volume/height stats
python -m pipeline.inspect_cityjson --tile 6204_105

# omit --tile to process every tile listed in config.yml
```

Build the roofer image once (the source tarball in `roofer-1.0.0/`):

```bash
docker build -f roofer-1.0.0/docker/Dockerfile --build-arg JOBS=10 \
  -t roofer:1.0.0 roofer-1.0.0
```

Outputs land in `out/work/<tile>/` (prepared LAS, roofprints, DTM, roofer TOML),
`out/roofer/<tile>/` (CityJSON) and `out/qa/` (QA record per tile).

Two facts about roofer 1.0.0 worth keeping in mind, both established from its
source and `--help-all` rather than from its example configs:

- It keeps a point **only** if the classification equals `bld-class` (6) or
  `grnd-class` (2) — `src/extra/io/StreamCropper.cpp`. Every other class is
  discarded, class 12 included. This is why Phase 1 writes a prepared LAS.
- `apps/roofer-app/example_full.toml` is stale. It documents a `lod = 22` key
  the binary rejects (LoD is set by `lod12`/`lod13`/`lod22` booleans) and a
  `complexity-factor` of 0.7 against an actual default of 0.888. Take
  parameters from `roofer --help-all`.

The built image does **not** include val3dity (`use_val3dity=False` in the
upstream Dockerfile), so no `rf_val3dity_*` attributes are emitted. Phase 3
needs val3dity installed separately.

## Conventions

- Config-driven, one command per tile. No hardcoded paths.
- Every pipeline stage writes a QA record: counts in, counts out, failures.
- Cite Peters et al. (roofer/3DBAG), Huang et al. (City3D), Nan & Wonka
  (PolyFit), Biljecki et al. (LOD spec) in anything published.
