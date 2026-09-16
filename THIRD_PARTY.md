# Third-party components

This project is licensed **GPL-3.0-or-later** ([LICENSE](LICENSE)). The components
below are not ours and carry their own terms.

---

## roofer — the reconstruction engine

|  |  |
|---|---|
| Upstream | https://github.com/3DBAG/roofer |
| Version | **1.0.0** (release tag `v1.0.0`) |
| Licence | GPL-3.0 |
| Modified? | **No.** Used entirely as published. |
| Distributed here? | **No.** Installed by the user from upstream. |

### How it is used

roofer is invoked as a **separate process**. `src/roof_reconstruction/run_roofer.py` writes a TOML
configuration, runs the roofer executable (in a container or as a native binary),
and reads back the CityJSON it produces. No roofer code is linked, imported, copied
or vendored into this project, and no roofer binary is redistributed with it.

That separation is why this project could have carried any licence it liked. GPL-3.0
was chosen deliberately, not because roofer's copyleft reached it.

### Obtaining it

Official builds only — nothing needs to be compiled:

```bash
docker pull 3dgi/roofer:v1.0.0
```

or a native binary from
[github.com/3DBAG/roofer/releases/tag/v1.0.0](https://github.com/3DBAG/roofer/releases/tag/v1.0.0):
`roofer-windows-x86_64-v1.0.0.zip`, `roofer-linux-x86_64-v1.0.0.tar.gz`,
`roofer-macOS-arm64-v1.0.0.tar.gz`.

roofer's own source, required to exercise your GPL-3.0 rights over it, is at the
upstream repository under the same `v1.0.0` tag.

### Note on val3dity

The published image is built with `use_val3dity=False`, so roofer emits no
`rf_val3dity_*` attributes. Geometric validation requires
[val3dity](https://github.com/tudelft3d/val3dity) installed separately. Verified
against `3dgi/roofer:v1.0.0` on 2026-09-16.

---

## citygml-tools — the CityGML converter

|  |  |
|---|---|
| Upstream | https://github.com/citygml4j/citygml-tools |
| Version | **2.5.0** (Docker tag `2.5.0` — no leading `v`) |
| Licence | Apache-2.0 |
| Modified? | **No.** |
| Distributed here? | **No.** Installed by the user from upstream. |

Used only by the CityGML export. `src/model_export/citygml.py` runs its
`from-cityjson` command on the merged `<tile>.city.json`, in the official image or
as a native install, and reads back the `.city.gml` it writes — the same
separate-process arrangement as roofer.

```bash
docker pull citygml4j/citygml-tools:2.5.0
```

The native route needs a Java runtime; the official image ships Java 21, so that
version is known to work — check the upstream release notes for the minimum.
Verified against the `2.5.0` image on 2026-09-16.

---

## Python dependencies

Installed from PyPI via [requirements.txt](requirements.txt); none are redistributed
here.

| Package | Version | Licence |
|---|---|---|
| geopandas | 1.1.3 | BSD-3-Clause |
| shapely | 2.1.2 | BSD-3-Clause |
| pyproj | 3.7.2 | MIT |
| laspy | 2.7.0 | BSD-3-Clause |
| rasterio | 1.5.0 | BSD-3-Clause |
| numpy | 2.3.5 | BSD-3-Clause |
| scipy | 1.16.3 | BSD-3-Clause |
| pandas | 2.3.3 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| mapbox_earcut | 2.1.0 | ISC |

`geopandas`, `rasterio`, `pyproj` and `shapely` bundle GDAL, PROJ and GEOS, which
carry their own licences (MIT / X11-style and LGPL-2.1). Consult those projects if
you redistribute built wheels.

---

## Data

Neither dataset is included in this repository, and neither is ours to relicense.

| Dataset | Source | Notes |
|---|---|---|
| Laser point cloud (`*.las`) | Lantmäteriet — *Laserdata* | Swedish national open data |
| Building footprints | Lantmäteriet — *Byggnad, vektor* v1.6 | Check the product terms before redistributing any derived GeoPackage |

The footprint GeoPackage in `data/` is derived from the *Byggnad* product. Confirm
Lantmäteriet's terms before publishing it or committing it to a public repository.

---

## Referenced but not used

**City3D** (https://github.com/tudelft3d/City3D, GPL-3.0) and **PolyFit**
(https://github.com/LiangliangNan/PolyFit, GPL-3.0) are cited as comparison baseline
and background in [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md). Neither is used,
included, or invoked by this code.
