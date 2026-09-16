# Code guide

How this pipeline is put together, for a developer picking it up cold.

For *what it does and how to run it*, start with the [README](../README.md). For
*why each decision was made*, see [PROJECT_PLAN.md](PROJECT_PLAN.md). This file
covers the code itself.

---

## Data flow

```
Lantmäteriet Byggnad GPKG  ─┐
  (national, EPSG:3006)     │  src/pipeline/buildings/ "footprints" stage
                            └─► buildings_processed_postprocess.gpkg
                                       │
LAS tile (EPSG:3008) ──────────────────┤
                                       ▼
                            src/pipeline/prepare_tile.py   "prepare"  (Phase 1)
                              ├─ dtm.py       0.5 m terrain raster
                              ├─ recover.py   roof points, geometrically
                              ├─ footprints.py  offset measure + buffer sweep
                              ├─ diagnose.py  per-footprint failure catalogue
                              └─ tiling.py    core / buffered extents, ownership
                                       │
                                       ├─► <tile>_prepared.las     (roof = class 6)
                                       ├─► <tile>_roofprints.gpkg  (buffered)
                                       └─► <tile>_dtm.tif
                                       ▼
                            src/pipeline/run_roofer.py     "roofer"   (Phase 2)
                              writes a TOML, runs roofer as a subprocess
                                       │
                                       └─► out/roofer/<tile>/*.city.jsonl   ← deliverable
                                       ▼
                            src/pipeline/inspect_cityjson.py  "inspect" (Phase 3)
```

Every stage writes into a `TileQA` record (`qa_record.py`): counts in, counts out,
metrics, and named failures. One `out/qa/<tile>_qa.md` and `.json` per tile.

---

## Modules

### Entry point

| File | Role |
|---|---|
| `main.py` | Root shim: puts `src/` on `sys.path`, then calls `pipeline.cli`. Lets a clone run with nothing installed. |
| `src/pipeline/cli.py` | Every subcommand. Dispatches to each stage's own `main(argv)`; adds nothing but the `all` chain. Also the `helsingborg-lod22` console script. |

Each stage module also keeps its own CLI (`python -m pipeline.prepare_tile --tile X`,
with `src/` on `PYTHONPATH`), and `cli.py` calls those rather than duplicating them.
Adding a stage means adding a subparser plus one line in `cli.main()`.

### Core pipeline (`src/pipeline/`)

| File | Role |
|---|---|
| `config.py` | Loads `config.yml`, resolves every path against **the config file's own directory**. This is why commands work from any working directory. `Config.path()` is the single funnel — nothing builds paths by hand. |
| `io.py` | Reads LAS into float64 real-world coordinates (`PointCloud`), and footprints into a reprojected, exploded, validity-repaired GeoDataFrame. Assigns `bid`, the stable per-polygon id used end to end. |
| `dtm.py` | 1.1 — rasterises ground returns to a 0.5 m DTM, median per cell, gaps filled by exact nearest valid cell. |
| `recover.py` | 1.2 — the class-12 recovery. Selects roof candidates by height above the DTM, then filters vegetation by local surface variation (PCA over k neighbours). |
| `footprints.py` | 1.3 — measures the footprint→roofprint offset from the data and sweeps candidate buffers, scoring each by capture rate and annulus purity. |
| `diagnose.py` | 1.4 — resolves "footprint with no points" into a named cause. Not a debug script despite the name; it is a QA stage. |
| `tiling.py` | 1.5 — core vs buffered extents, and centroid-based ownership so a building straddling an edge is reconstructed once. |
| `qa_record.py` | The QA record itself: `TileQA` → `StageRecord`, written as JSON and Markdown. |
| `prepare_tile.py` | Phase 1 driver. Chains the above and writes the three prepared inputs. |
| `run_roofer.py` | Phase 2 driver. Builds the roofer TOML, runs roofer, logs it, records the result. |
| `inspect_cityjson.py` | Phase 3 driver. LoDs, semantic surfaces, roof forms, volume and height stats. |
| `cli.py` | Every subcommand; see above. |
| `fix_cityjson.py` | Standalone utility, not a stage. Strips bare `NaN` (which is not legal JSON) so strict viewers accept a file. |

### Footprints (`src/pipeline/buildings/`)

| File | Role |
|---|---|
| `base.py` | Abstract `load → validate → preprocess → export` template. `run()` returns a summary dict rather than raising. |
| `pipeline.py` | The Byggnad implementation, plus the value translators (`translate_purpose`, `purpose_category`, `translate_collection_level`). |
| `postprocess.py` | Collapses the version history to the newest row per `object_id`. Called from `export()`. |
| `translations.py` | Swedish → English lookup tables. Constants only — the YAML loader is `src/pipeline/config.py`. |

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
  docstring — `fix_cityjson` passes `__doc__` straight to argparse.

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

`diagnose.py` resolves an empty footprint into one of these, reported per building in
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
