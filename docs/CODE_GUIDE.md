# Code guide

How this pipeline is put together, for a developer picking it up cold.

For *what it does and how to run it*, start with the [README](../README.md). For
*why each decision was made*, see [PROJECT_PLAN.md](PROJECT_PLAN.md). This file
covers the code itself.

---

## Data flow

One folder per pipeline under `src/`, named for what it does. They run in this order:

```
Lantmäteriet Byggnad GPKG ─┐
  (national, EPSG:3006)    │  footprint_extraction/      python main.py footprints
                           └─► buildings_processed_postprocess.gpkg
                                      │
LAS tile (EPSG:3008) ─────────────────┤
                                      ▼
                           roofprint_preparation/      python main.py prepare   (Phase 1)
                             ├─► <tile>_prepared.las     roof points relabelled to class 6
                             ├─► <tile>_roofprints.gpkg  footprints buffered to the roof edge
                             └─► <tile>_dtm.tif
                                      ▼
                           roof_reconstruction/        python main.py roofer    (Phase 2)
                             └─► out/roofer/<tile>/*.city.jsonl   CityJSON 2.0 sequence
                                      ▼
                           model_export/               python main.py export
                             ├─► out/export/<tile>/<tile>.city.json   CityJSON 2.0
                             ├─► out/export/<tile>/<tile>.city.gml    CityGML (citygml-tools)
                             ├─► out/export/<tile>/<tile>.glb         glTF 2.0
                             └─► out/export/<tile>/<tile>.ply         PLY
                                      ▼
                           model_inspection/           python main.py inspect   (Phase 3)
```

`pipeline_common/` (config loader, QA record) is used by all of them, and
`run_pipeline/` is the command line that drives them.

Every stage writes into a `TileQA` record: counts in, counts out, metrics, and named
failures. One `out/qa/<tile>_qa.json`, `.md` and `.html` per tile.

---

## Modules

### Entry point

| File | Role |
|---|---|
| `main.py` | Root shim: puts `src/` on `sys.path`, then calls `run_pipeline.cli`. Lets a clone run with nothing installed. |
| `run_pipeline/cli.py` | Every subcommand. Dispatches to each stage's own `main(argv)`; adds nothing but the `all` chain. Also the `helsingborg-lod22` console script. |
| `run_pipeline/gui.py` | The Tkinter window. A front end only: each button runs the matching `main.py` command as a child process with the same interpreter and streams its output, so nothing is implemented twice. Adds setup checks (packages, Docker, images, input files) and buttons that open results. Opened by `Start GUI.bat`, `gui.pyw`, or `main.py gui`. |
| `gui.pyw`, `Start GUI.bat` | Launchers. `gui.pyw` imports only the GUI module, whose imports are standard library, so the window opens — and reports what to install — even when the pipeline's packages are missing. The `.bat` uses the `py -3.12` launcher, and must keep CRLF line endings (enforced in `.gitattributes`). |

Each driver also keeps its own CLI (`python -m roofprint_preparation.prepare_tile --tile X`,
with `src/` on `PYTHONPATH`), and `cli.py` calls those rather than duplicating them.
Adding a stage means adding a subparser plus one line in `cli.main()`, and a button
in `gui.py` if it should be reachable from the window.

### `pipeline_common/` — shared

| File | Role |
|---|---|
| `config.py` | Loads `config.yml`, resolves every path against **the config file's own directory**. This is why commands work from any working directory. `Config.path()` is the single funnel — nothing builds paths by hand. |
| `qa_record.py` | The QA record itself: `TileQA` → `StageRecord`, written as JSON, Markdown and HTML. Each phase runs as its own process, so `write()` merges into the tile's existing report — a stage replaces only its own earlier record. |
| `qa_report_html.py` | Renders the QA record as one self-contained HTML page: stage overview, flagged buildings across stages, plain-language failure explanations. New stages and failure kinds need an entry in `STAGE_TITLES` / `FAILURE_HELP` to get a friendly label; without one they still render, under their raw name. |
| `containers.py` | Runs an external tool in Docker or as a native binary, and rebases paths onto the container mount. Shared by roofer and citygml-tools. |

### `footprint_extraction/` — cadastral footprints

| File | Role |
|---|---|
| `base.py` | Abstract `load → validate → preprocess → export` template. `run()` returns a summary dict rather than raising. |
| `byggnad_pipeline.py` | The Byggnad implementation, plus the value translators (`translate_purpose`, `purpose_category`, `translate_collection_level`). |
| `dedup_snapshot.py` | Collapses the version history to the newest row per `object_id`. Called from `export()`. |
| `translations.py` | Swedish → English lookup tables. Constants only. |

### `roofprint_preparation/` — Phase 1

| File | Role |
|---|---|
| `readers.py` | Reads LAS into float64 real-world coordinates (`PointCloud`), and footprints into a reprojected, exploded, validity-repaired GeoDataFrame. Assigns `bid`, the stable per-polygon id used end to end. |
| `dtm.py` | 1.1 — rasterises ground returns to a 0.5 m DTM, median per cell, gaps filled by exact nearest valid cell. |
| `overlap_recovery.py` | 1.2 — the class-12 recovery. Selects roof candidates by height above the DTM, then filters vegetation by local surface variation (PCA over k neighbours). |
| `roofprint_offset.py` | 1.3 — measures the footprint→roofprint offset from the data and sweeps candidate buffers, scoring each by capture rate and annulus purity. |
| `footprint_diagnosis.py` | 1.4 — resolves "footprint with no points" into a named cause. |
| `tiling.py` | 1.5 — core vs buffered extents, and centroid-based ownership so a building straddling an edge is reconstructed once. |
| `prepare_tile.py` | The Phase 1 driver. Chains the above and writes the three prepared inputs. |

### `roof_reconstruction/` — Phase 2

| File | Role |
|---|---|
| `run_roofer.py` | Builds the roofer TOML, runs roofer, logs it, records the result. |

### `model_export/` — delivery formats

| File | Role |
|---|---|
| `cityjson_sequence.py` | Reads roofer's `.city.jsonl`; merges it into one CityJSON document by offsetting each feature's vertex indices. Quantised vertices are copied untouched. |
| `citygml.py` | Runs citygml-tools `from-cityjson` on the merged file. CityGML is never written by hand. |
| `triangulate.py` | Planar faces → triangles by ear clipping (`mapbox_earcut`), with a semantic code per triangle. Winding is decided once per face, from the area-weighted normal. |
| `gltf_writer.py` | Binary glTF: root node with georeference, one node per building with attributes in `extras`, one primitive and material per semantic class. Recentred and Y-up. |
| `ply_writer.py` | Binary PLY: real-world `double` vertices, per-face colour, `building` and `semantic`. |
| `export_models.py` | The driver: picks formats, writes them, records the `3-export` QA stage. |

Two rules the mesh code depends on:

- **Recentre before arithmetic.** Normals, areas and volumes are computed on
  coordinates minus a local mean. At 6.2 × 10⁶ m, products of raw coordinates lose
  the precision those numbers need. Only glTF *stores* recentred coordinates, because
  float32 forces it; the origin goes in the file.
- **Decide triangle winding per face, never per triangle.** roofer's outlines carry
  near-collinear vertices quantised to 1 mm; the sliver triangles they produce have
  normals that are pure noise. Judging each triangle on its own flipped some and
  cracked two otherwise closed buildings on tile 6204_105.
  `tests/test_export.py` pins an exact face that reproduces it.

### `model_inspection/` — Phase 3

| File | Role |
|---|---|
| `inspect_cityjson.py` | LoDs, semantic surfaces, roof forms, volume and height stats. |
| `repair_cityjson.py` | Standalone utility, not a stage. Strips bare `NaN` (which is not legal JSON) so strict viewers accept a file. |

---

## Conventions

- **`main(argv=None) -> int`**, ended by `raise SystemExit(main())`. Exit `0` success,
  `1` stage failure, `2` configuration error.
- **`--tile` is optional everywhere.** Omitted, a stage fans out over every tile in
  `config.yml`.
- **No hardcoded paths.** Everything resolves through `Config`.
- **Every stage writes a QA record**, including its failures.
- **`from __future__ import annotations`** first in every core module; PEP 604
  (`X | None`) types throughout.
- **Docstrings justify decisions, not mechanics.** Where a module rejects an obvious
  alternative, it says why — that reasoning is the expensive part and it is kept in
  the code rather than in a separate document.
- British spelling, and an SPDX + author header above (never inside) the module
  docstring — `repair_cityjson` passes `__doc__` straight to argparse.

---

## Where to change what

| To change… | Edit |
|---|---|
| Which tiles are processed | `config.yml` → `tiles:` |
| Input or output locations | `config.yml` → `paths:` |
| DTM resolution, ground classes | `config.yml` → `dtm:` |
| Which classes are recovered, the 2 m height threshold | `config.yml` → `recover:` |
| Vegetation filter aggressiveness | `config.yml` → `recover.planarity.max_surface_variation` |
| Roofprint buffer (or let the sweep choose) | `config.yml` → `footprints.buffer` |
| Docker vs native roofer, image tag | `config.yml` → `roofer.runner` / `image` |
| Which LoDs roofer emits | `config.yml` → `roofer.lod12/lod13/lod22` |
| Plane detection sensitivity | `config.yml` → `roofer.reconstruction` |
| Which export formats are written | `config.yml` → `export.formats`, or `--format` per run |
| CityGML 2.0 vs 3.0 | `config.yml` → `export.citygml.version` |
| Which LoD goes into glTF / PLY | `config.yml` → `export.lod` |
| Roof / wall / ground colours | `config.yml` → `export.mesh.colours` |

Several `config.yml` values are calibrated rather than chosen, and the comment above
each records the evidence. `recover.planarity.max_surface_variation: 0.06` is the
clearest example — the comment gives the sensitivity sweep and the reason 0.06 sits
in the usable band. Read the comment before changing the number.

---

## Two roofer facts worth knowing

Both established from roofer's source and `--help-all`, not from its example configs.

1. **roofer keeps a point only if its classification equals `bld-class` (6) or
   `grnd-class` (2)** — `src/extra/io/StreamCropper.cpp`. Everything else is dropped,
   class 12 included. This is the entire reason Phase 1 writes a prepared LAS with
   recovered roof points relabelled to 6. Feed roofer the raw tile and it silently
   discards the 861k class-12 returns that Phase 1 exists to recover.

2. **`apps/roofer-app/example_full.toml` is stale.** It documents a `lod = 22` key the
   binary rejects — LoD is set by the `lod12` / `lod13` / `lod22` booleans — and a
   `complexity-factor` of 0.7 against an actual default of 0.888. Take parameters from
   `roofer --help-all`.

---

## Failure reasons

`footprint_diagnosis.py` resolves an empty footprint into one of these, reported per building in
`out/qa/<tile>_per_building.csv`:

| Reason | Meaning | What to do |
|---|---|---|
| `ok` | Roof points found | — |
| `edge_clipped` | Most of the polygon is outside point coverage | Expected at tile edges; the tile buffer handles it |
| `no_returns` | No returns of any class | A void in the LiDAR; nothing to do |
| `below_height_threshold` | Returns exist, none above `recover.min_height_above_dtm` | Usually a low shed or garage; lower the threshold if these matter |
| `absent_building` | Returns exist and are mostly ground | The cadastral record is stale — the building is gone |
| `no_roof_points` | Tall returns exist, none survived filtering | Check the planarity threshold |

---

## Testing a change

```bash
python tests/test_translations.py                  # attribute translation, no runner needed
python tests/test_export.py                        # triangulation, merge, glTF/PLY round trips
python main.py roofer --tile 6204_105 --dry-run   # inspect the TOML and command
python main.py all --tile 6204_105                 # full run
python main.py inspect --tile 6204_105             # compare the numbers
```

The reference tile `6204_105` should give **66 buildings**, 61 with LOD2.2 geometry,
a median volume near 255 m³ and a median height near 5.2 m. A volume in the 10⁸ m³
range means something recentred coordinates wrongly — at 6.2 × 10⁶ m the
divergence-theorem sum loses all precision, and that bug once produced 5 × 10⁸ m³ for
a single house.

Run `main.py` from a directory other than the repo root now and then: it is the only
check that config discovery and root-relative path resolution still hold.
