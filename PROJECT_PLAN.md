# LOD2.2 Building Reconstruction — Helsingborg

Project brief for an AI coding agent. Read this whole file before writing code.

---

## 1. Goal

Produce **LOD2.2** 3D building models for Helsingborg from airborne LiDAR and
cadastral footprints. Output as **CityJSON** with semantic surfaces
(RoofSurface / WallSurface / GroundSurface), geometrically valid and watertight.

Student research project. Will be released open source. Result quality matters
more than novelty.

**LOD2.2 means:** per-building solids with differentiated roof shapes
(gable / hip / flat / shed), roof overhangs, flat walls, no facade detail,
semantic surfaces separated. LOD2.3 additionally models roof superstructures
(dormers, chimneys) as separate features — treat that as a stretch goal only.

---

## 2. The central decision

**Use `roofer` as the reconstruction engine. Do not write the reconstruction
algorithm from scratch.**

A from-scratch Python prototype has already been built and evaluated. It works —
27 buildings, all closed and orientable, 22 seconds — but the output is visibly
noisy: over-segmented roof planes, ragged outlines, fragmented partitions on
terraced rows. The noise comes from missing regularisation, not from Python.
Rewriting the same algorithm in C++ would produce the same noisy mesh, faster.

`roofer` is the production tool behind 3DBAG (10M buildings, all of the
Netherlands). It has years of regularisation work in it. Use it.

| Tool | Role in this project |
|---|---|
| **roofer** (`github.com/3DBAG/roofer`) | Primary engine. GPL-3.0. C++ with Python bindings. Outputs CityJSONSequence at LoD1.2 / 1.3 / 2.2. |
| **City3D** (`github.com/tudelft3d/City3D`) | Comparison baseline, and the codebase to fork if a research contribution is needed. GPL-3.0. Research prototype, outputs meshes without CityGML semantics. |
| **PolyFit** (`github.com/LiangliangNan/PolyFit`) | Citation / background only. Requires pre-segmented planar segments and assumes a closed model — neither holds for airborne LiDAR. Also available inside CGAL as `Polygonal_surface_reconstruction`. |

All three are GPL-3.0. Running roofer as a separate process and consuming its
CityJSON creates no licensing obligation. Copying source into our code makes our
code GPL-3.0 on distribution — acceptable here, since this project is open source
anyway.

---

## 3. Data

### Point cloud
- Sample tile: `6204_105_hbg.las`, LAS 1.2, 2,259,865 points
- Extent 236 × 193 m, density **49.6 pts/m²** — high, more than enough for LOD2.2
- CRS **EPSG:3008** (SWEREF99 13 30), projected, metres
- Full source: Lantmäteriet open laserdata

**Classification breakdown — read this carefully, it matters:**

| Class | Meaning | Count | Share |
|---|---|---|---|
| 1 | Unclassified | 138,067 | 6.1% |
| 2 | Ground | 735,805 | 32.6% |
| 3/4/5 | Vegetation | 65,803 | 2.9% |
| 6 | **Building** | 265,766 | 11.8% |
| 7 | Noise | 6,533 | 0.3% |
| 11 | Road | 186,627 | 8.3% |
| 12 | **Overlap** | 861,264 | **38.1%** |

**Class 12 is the single biggest data trap.** Overlap points are flight-strip
overlap returns that were set aside during classification — they carry no
semantic label, but many of them sit on roofs. Their Z range is 13.4–34.7 m
against a ground level near 15.7 m, and ~27% of them fall within 1 m of a
class-6 point in XY.

Filtering on `classification == 6` alone discards most of the roof. Verified:
recovering classes 1 and 12 geometrically (anything > 2 m above a rasterised DTM)
raises usable roof points from **199,968 → 487,397** on this tile, a 2.4× gain.

### Footprints
- `buildings_processed_postprocess.gpkg`, layer `buildings_postprocess`
- 2,762 polygons, **EPSG:3006** (SWEREF 99 TM) — must be reprojected to 3008
- Stored as single-part MultiPolygons; explode to Polygon at load
- 69 fall inside the sample tile

**Footprint vs roofprint:** roofer wants a *roofprint* — the outline of the roof
seen from above, including eaves. Cadastral polygons are ground footprints and sit
inside the roof outline. In the prototype only 75% of class-6 points fell inside a
footprint; eave overhang is part of that. Buffer the footprints outward before
use, and calibrate the amount (see Phase 1).

---

## 4. Phases

### Phase 0 — Environment

**Goal:** roofer and City3D both build and run.

1. Build roofer. Prefer the **Docker image** from the 3DBAG GitHub packages —
   it avoids the CGAL/Conan dependency chain entirely. Build from source only if
   Docker is unavailable.
2. Build City3D (CMake + CGAL 5.6 + OpenCV 4.x; Qt only for the GUI demo, the
   two CLI examples build without it). SCIP is bundled; obtain a **free academic
   Gurobi licence** — it is substantially faster than SCIP on the integer program.
3. Install `val3dity` for geometric validation.
4. Python side: `laspy`, `pdal`, `geopandas`, `shapely`, `rasterio`, `numpy`,
   `scipy`, `cjio` (CityJSON manipulation).

**Acceptance:** roofer reconstructs its own sample data; City3D runs
`CLI_Example_1` on its bundled test data.

**Warning:** budget a week for this and no more. Dependency setup is not the
research. If the source build stalls, use Docker and move on.

---

### Phase 1 — Data preparation and QA

**Goal:** clean, aligned, measured inputs. Do this before touching any
reconstruction engine — it determines most of the output quality.

**1.1 Ground and DTM**
- Extract class 2, build a rasterised DTM at 0.5 m with `PDAL` or `rasterio`
- Fill gaps by nearest-valid-cell (there are no ground returns under buildings)
- Sample from the raster, not by spatial query per building — a per-building
  `.within()` scan over 735k points is orders of magnitude slower

**1.2 Recover the overlap class**
- Build the candidate roof-point set as: class 6, **plus** classes 1 and 12
  where height above DTM > 2.0 m
- Filter residual vegetation by local planarity (normal consistency in a small
  neighbourhood), not by class label
- Report before/after point counts per building

**1.3 Measure the footprint/roofprint offset — do not guess it**
- Reproject footprints 3006 → 3008, explode to single-part Polygons
- For each building, compute the median signed distance from roof points that
  fall *outside* the polygon to the polygon boundary
- If the offset is systematic (expect roughly 0.3–0.8 m), that is the buffer
  distance
- Sweep buffer ∈ {0.0, 0.25, 0.5, 0.75, 1.0} and pick by point-capture rate and
  visual roof-edge quality

**1.4 CRS hygiene**
- Everything in EPSG:3008 end to end
- **Do not translate coordinates to a local frame.** roofer handles real-world
  coordinates. (The prototype's local-frame translation caused a latent bug:
  GeoDataFrames were tagged `crs="EPSG:3008"` while holding translated
  coordinates. It worked only because both sides matched.)
- Do recentre before any volume computation — at 6.2e6 m the signed sum in the
  divergence theorem loses all precision. This bug produced 5×10⁸ m³ for a house.

**1.5 Tiling**
- Tile point cloud and footprints on a common grid with a buffer overlap so
  buildings on tile edges are complete

**Acceptance:** a QA report per tile — point counts by class, recovered-point
gain, point-capture rate per footprint, chosen buffer distance, count of
footprints with no points.

---

### Phase 2 — Run roofer

**Goal:** LOD2.2 CityJSON for the sample tile.

1. Run roofer on tile `6204_105` with the Phase 1 inputs
2. Inspect ~20 buildings in **ninja.cityjson.org** (browser, no install) or QGIS
3. Tune reconstruction parameters against 49.6 pts/m² — the defaults are set for
   Dutch AHN density, which is lower. Expect to adjust plane-detection thresholds.
4. Check how roofer selects building points from the cloud — whether it uses the
   classification or clips by footprint. This is the **single biggest quality
   lever** given the class-12 problem. If it filters on class 6, pre-filter the
   LAS yourself and feed it a cloud where the recovered points are relabelled 6.

**Acceptance:** LOD2.2 CityJSON for the tile; ≥95% of buildings pass val3dity;
visual inspection shows correct roof forms on gable, hip and flat examples.

---

### Phase 3 — Validation and benchmarking

**Goal:** know how good the output is, in numbers. This is the publishable part.

**3.1 Benchmark set**
Assemble several km² of Helsingborg covering: detached gable houses, **terraced
rows** (the hardest case — see §5), flat-roof apartment blocks, industrial sheds,
complex/historic roofs. Target a few hundred buildings, manually checked.

**3.2 Metrics**
- Point-to-surface RMSE (roof points vs reconstructed roof faces)
- Roof-plane recall — compare against an independent RANSAC plane count per
  building. The existing Python prototype already produces plane count, tilt and
  mean height per plane; **keep it as the QA harness.** It is an independent
  estimate of how many roof planes a building should have.
- Geometric validity via val3dity (watertight, no self-intersection)
- Volume and height error where reference data exists
- Runtime and memory per km²

**3.3 Comparison**
Run City3D (`CLI_Example_1`, footprints + point cloud) on the same benchmark.
Report roofer vs City3D head to head.

**This comparison is itself a contribution** — the published evaluations of these
tools cover Dutch and French data, not Nordic building stock.

**Acceptance:** a metrics table over the benchmark set, both engines, with
failure cases catalogued by building type.

---

### Phase 4 — Scale

- Parallelise by tile
- Merge per-tile CityJSON, deduplicate buildings in overlap zones
- Automated QA gate: flag implausible height, volume, plane count, or val3dity
  failure for manual review

**Acceptance:** full study area processed, QA report, reproducible from a single
command.

---

### Phase 5 — Research contribution (choose one)

Pick based on what actually fails in Phase 3.

**Option A — Flight-strip overlap handling.** The class-12 problem is real,
general, and unaddressed by either engine. A principled method for recovering and
reclassifying overlap returns would benefit anyone working with multi-strip ALS.
*Lowest risk, clear value.*

**Option B — Automatic footprint↔roofprint alignment.** Swedish cadastral
outlines have different provenance from Dutch BAG. An automatic estimation and
correction step, validated across building types. *Medium risk.*

**Option C — LOD2.3.** Detect dormers and chimneys as residual planar clusters
above the fitted roof surfaces; emit as building parts. No open-source tool does
this well. *Highest value, highest risk. Do not start here.*

If forking is required, fork **City3D** — its optimisation is localised in
`face_selection_optimization.cpp` and is far easier to intervene in than roofer's
pipeline.

---

## 5. Known hard cases

**Terraced rows are the main failure mode.** Connected-component labelling on the
point cloud merges houses that touch, giving one "building" with 8–10 roof planes,
and the plane-intersection partition then fragments into slivers. The cadastral
footprints solve this by separating the houses — *this is the main reason to use
real footprints rather than deriving outlines from the cloud.*

Two filters help if any partitioning is done in-house:
- only let *spatially adjacent* plane pairs contribute an intersection line
- keep a candidate ridge only if **both** planes have points hugging it,
  otherwise it is a phantom line slicing through neighbouring houses

**Vegetation touching walls** and **buildings at tile edges** are the other two
recurring sources of bad geometry.

---

## 6. Do not do these

Each of these was tried and cost time.

- **Do not mesh the whole scene and segment buildings out afterwards.** LOD2.2
  needs per-building solids with roof topology and semantics. A full-scene
  triangle soup has none of that, and building/ground/vegetation boundaries smear
  together. Segment first, always footprint-driven.
- **Do not use per-plane convex hulls as roof faces.** Convex hulls of plane
  inliers *overlap*. The resulting prisms interpenetrate, volumes double-count,
  and no valid solid is possible. LOD2.2 needs a planar *partition* — disjoint
  cells that tile the footprint exactly.
- **Do not use `scipy.spatial.Delaunay` for roof faces.** It triangulates the
  convex hull, so it cannot respect an L-shaped outline, and it introduces
  vertices the wall quads do not share — T-junctions, hence non-watertight. If
  triangulation is needed, use ear clipping (`mapbox_earcut`) or a constrained
  Delaunay (`triangle`, CGAL `Constrained_Delaunay_triangulation_2`), which add
  no Steiner points on boundaries.
- **Do not filter on `classification == 6`.** See §3.
- **Do not port the reconstruction algorithm to C++ hoping for better output.**
  Language affects speed and memory, not geometric resolution. Both use float64.
- **Do not rewrite the Python prototype.** Keep it as the validation harness.

---

## 7. Deliverables

1. Reproducible pipeline, one command per tile, config-driven
2. LOD2.2 CityJSON for the study area, val3dity-clean
3. QA report: per-tile statistics, failure catalogue
4. Benchmark comparison roofer vs City3D on Swedish building stock
5. Public repository, GPL-3.0, citing:
   - Peters, Dukai, Vitalis, van Liempt, Stoter — *Automated 3D reconstruction of
     LoD2 and LoD1 models for all 10 million buildings of the Netherlands* (2022)
   - Huang, Stoter, Peters, Nan — *City3D: Large-scale Building Reconstruction
     from Airborne LiDAR Point Clouds*, Remote Sensing 14(9), 2254 (2022)
   - Nan & Wonka — *PolyFit: Polygonal Surface Reconstruction from Point Clouds*,
     ICCV 2017
   - Biljecki, Ledoux, Stoter — *An improved LOD specification for 3D building
     models*, CEUS 59:25–37 (2016) — for the LOD2.2 definition itself

---

## 8. Order of work

Phase 0 and Phase 1 can run in parallel. **Phase 1 is not optional and not a
formality** — the class-12 recovery and the footprint buffer calibration will
change the output more than any parameter tuning in Phase 2.

Do not begin Phase 5 until Phase 3 has produced numbers showing what actually
fails.
