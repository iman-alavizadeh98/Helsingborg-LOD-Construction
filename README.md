# LOD2.2 Building Reconstruction — Helsingborg

Airborne LiDAR plus cadastral footprints in, semantically-structured 3D building
models out, as **CityJSON at LOD2.2**: one solid per building, differentiated roof
shapes, and RoofSurface / WallSurface / GroundSurface separated.

Author: **Iman Alavi Zadeh** — developed with AI-assisted (agentic) programming.
Licensed under **GPL-3.0-or-later**; see [LICENSE](LICENSE) and
[THIRD_PARTY.md](THIRD_PARTY.md).

---

## What it produces

For each tile, in `out/`:

| File | What it is |
|---|---|
| `roofer/<tile>/*.city.jsonl` | The deliverable — LOD2.2 CityJSONSequence |
| `work/<tile>/<tile>_prepared.las` | Cleaned cloud: ground + recovered roof points |
| `work/<tile>/<tile>_roofprints.gpkg` | Footprints buffered out to the roof edge |
| `work/<tile>/<tile>_dtm.tif` | Gap-filled terrain raster, 0.5 m |
| `qa/<tile>_qa.md` | Per-stage QA report: counts in, counts out, failures |
| `qa/<tile>_per_building.csv` | Per-building diagnostics |

On the reference tile `6204_105` (236 × 193 m, 2.26 M points) that is 66 buildings,
reconstructed in about 16 seconds.

---

## Install

### 1. Python

Python **3.12** with the pinned dependencies:

```bash
python -m pip install -r requirements.txt
```

> On the development machine a bare `python` resolves to a miniforge base that
> lacks these packages and dies at `import yaml`. Use the standalone 3.12 install
> (`C:/Users/imana/AppData/Local/Programs/Python/Python312/python.exe`) or a fresh
> virtual environment.

### 2. roofer

roofer is the reconstruction engine. It is **not bundled** with this project — it
runs as a separate process, and you install the official 1.0.0 build. Either path
works; the pipeline supports both.

**Docker** (the default in `config.yml`):

```bash
docker pull 3dgi/roofer:v1.0.0
```

**Native binary — no Docker required.** Download the asset for your platform from
[github.com/3DBAG/roofer/releases/tag/v1.0.0](https://github.com/3DBAG/roofer/releases/tag/v1.0.0):

| Platform | Asset |
|---|---|
| Windows | `roofer-windows-x86_64-v1.0.0.zip` |
| Linux | `roofer-linux-x86_64-v1.0.0.tar.gz` |
| macOS (Apple silicon) | `roofer-macOS-arm64-v1.0.0.tar.gz` |

Extract it, put its `bin/` directory on `PATH`, then set `runner: native` in
`config.yml`.

### 3. Data

Two inputs, neither checked into this repository:

- **Point cloud** — LAS/LAZ tiles in `data/`, EPSG:3008. Open data from
  Lantmäteriet (*Laserdata*).
- **Cadastral footprints** — `data/buildings_processed_postprocess.gpkg`, layer
  `buildings_postprocess`. Produced by the `footprints` stage below from
  Lantmäteriet's national *Byggnad* vector product.

Point `config.yml` at them and list your tiles under `tiles:`.

---

## Run

Everything goes through `main.py`. Paths inside `config.yml` resolve against its own
directory, so these work from anywhere.

```bash
# the usual command — prepare, reconstruct, inspect
python main.py all --tile 6204_105

# or one stage at a time
python main.py prepare --tile 6204_105   # DTM, point recovery, roofprints
python main.py roofer  --tile 6204_105   # reconstruct
python main.py inspect --tile 6204_105   # LoDs, roof forms, volume/height stats

# omit --tile to process every tile in config.yml
# add --dry-run to the roofer stage to see the command and TOML without running
```

Regenerating the cadastral footprints from the raw national extract is a separate,
occasional job — it is not part of `all`:

```bash
python main.py footprints --input path/to/byggnad_sverige.gpkg --output data
```

View the result by dropping a `.city.jsonl` file into
[ninja.cityjson.org](https://ninja.cityjson.org), or open it in QGIS.

---

## How it works

Three phases. The detail is in [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md); the
research background and the reasoning behind each decision is in
[docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md).

**Phase 1 — preparation** is where most of the output quality is decided.

1. Rasterise a 0.5 m DTM from ground returns and fill gaps by nearest valid cell.
2. Recover roof points **geometrically**, not by class label. This matters more
   than anything else here: 38% of this data is ASPRS class 12 (flight-strip
   overlap), carrying no semantic label but most of the roof. Taking class 6 alone
   gives 199,968 usable roof points; adding classes 1 and 12 where the height above
   the DTM exceeds 2 m gives **487,397** — a 2.4× gain.
3. Drop residual vegetation by local surface planarity, again not by class.
4. Measure the footprint-to-roofprint offset from the data and sweep candidate
   buffers, reporting point-capture rate against annulus purity.
5. Write a prepared LAS with recovered roof points relabelled to class 6 — roofer
   keeps only points matching `bld-class` or `grnd-class` and discards the rest, so
   an unrelabelled cloud would silently throw the recovered points away again.

**Phase 2 — reconstruction** generates a roofer TOML and runs roofer.

**Phase 3 — inspection** reports LoDs, semantic surfaces, roof forms, and volume
and height distributions.

Every stage writes a QA record — counts in, counts out, failures with reasons.

---

## Known limitations

- **val3dity is not included.** The official roofer image is built with
  `use_val3dity=False`, so no `rf_val3dity_*` attributes are emitted. Geometric
  validation needs val3dity installed separately.
- **The independent QA harness is absent.** See [docs/QA_HARNESS.md](docs/QA_HARNESS.md) — this
  blocks roof-plane recall metrics specifically, not the pipeline.
- **Terraced rows are the known hard case.** Always use real cadastral footprints
  rather than outlines derived from the point cloud; connected-component labelling
  merges houses that touch.
- **The shipped footprint GeoPackage predates a translation fix.** Its
  `primary_purpose_en` and `primary_purpose_category` columns are wrong (everything
  categorised `Other`). The code is fixed; regenerating the file needs the raw
  Lantmäteriet *Byggnad* extract. Geometry is unaffected, so reconstruction output
  is unchanged — only those two attribute columns.
- **Single-tile flow.** Multi-tile cutting and cross-tile merge exist in the code
  (`tiling.build_grid`) but are not yet wired into a study-area run.

---

## Layout

```
main.py                      # run from a clone: puts src/ on the path, calls run_pipeline.cli
config.yml                   # all paths and parameters; no hardcoded paths in the code
pyproject.toml               # optional `pip install -e .`, gives the helsingborg-lod22 command
requirements.txt             # pinned, verified dependency set

src/
  footprint_extraction/      # Byggnad GPKG -> cadastral footprints, Swedish -> English
  roofprint_preparation/     # Phase 1: DTM, class-12 recovery, roofprint buffer, tiling
  roof_reconstruction/       # Phase 2: roofer
  model_inspection/          # Phase 3: inspect and repair CityJSON
  pipeline_common/           # shared config loader and QA records
  run_pipeline/              # the command line (every subcommand)

tests/               # regression tests, no runner required
docs/                # code guide, QA harness notes, project background
data/                # LAS tiles, footprint GeoPackage (not in git)
out/                 # CityJSON, QA reports (not in git)
```

---

## Citation

If you use this work, cite the tools it stands on:

- Peters, Dukai, Vitalis, van Liempt, Stoter — *Automated 3D reconstruction of LoD2
  and LoD1 models for all 10 million buildings of the Netherlands* (2022)
- Huang, Stoter, Peters, Nan — *City3D: Large-scale Building Reconstruction from
  Airborne LiDAR Point Clouds*, Remote Sensing 14(9), 2254 (2022)
- Nan & Wonka — *PolyFit: Polygonal Surface Reconstruction from Point Clouds*,
  ICCV 2017
- Biljecki, Ledoux, Stoter — *An improved LOD specification for 3D building models*,
  CEUS 59:25–37 (2016)
