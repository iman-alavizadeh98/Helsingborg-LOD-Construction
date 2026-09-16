# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""
Buildings dataset pipeline — cadastral footprints, Swedish → English.

Turns Lantmäteriet's national *Byggnad* vector GeoPackage into the footprint
layer the reconstruction pipeline consumes. This is the upstream producer of
``data/buildings_processed_postprocess.gpkg`` (layer ``buildings_postprocess``),
which ``config.yml`` names as ``paths.footprints``.

Four stages, inherited from :class:`~.base.BasePipeline`:

1. ``load``       — read the GeoPackage, Swedish column names untouched
2. ``validate``   — CRS, geometry validity, required fields, null coverage
3. ``preprocess`` — rename columns to English, translate coded values
4. ``export``     — write the processed GeoPackage, the deduplicated snapshot,
                    and the metadata/summary/report JSON

Run it with ``python main.py footprints``.

Note this stage is about *attributes*. The reconstruction pipeline reads only
geometry from the result and assigns its own ``bid`` (``pipeline/io.py``), so
nothing here changes the shape of a roof. The attributes matter for filtering and
for reporting, not for the solids.
"""

from pathlib import Path
import geopandas as gpd
import logging
import json
import numpy as np

from .base import BasePipeline
from .postprocess import build_postprocess_snapshot
from .translations import (
    FIELD_TRANSLATIONS,
    BUILDING_TYPES,
    PRIMARY_PURPOSES,
    COLLECTION_LEVELS,
    DATASET_METADATA,
)

logger = logging.getLogger(__name__)

# Purpose values that carry no information and should defer to the type half.
# "Ospecificerad" is Lantmäteriet's explicit "unspecified", and an empty string is
# what a type-only value like "Komplementbyggnad;" leaves behind after the split.
_UNSPECIFIED_PURPOSES = {"", "ospecificerad"}


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that understands the numpy scalars pandas hands back.

    ``value_counts().to_dict()`` yields numpy int64 keys and values, which the
    stdlib encoder refuses. Without this the summary export dies on its own output.
    """

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# ---------------------------------------------------------------------------
# Value translation
#
# `andamal1` is compound: "<Type>;<Purpose>", e.g. "Bostad;Småhus friliggande",
# and very often type-only with a trailing semicolon, e.g. "Komplementbyggnad;".
# The lookup tables are keyed on the halves, never on the compound string, so
# every translation below has to split first.
# ---------------------------------------------------------------------------

def split_purpose(value) -> tuple[str | None, str | None]:
    """Split a compound ``andamal`` value into ``(type_sv, purpose_sv)``.

    Either half may come back ``None``. A purpose that merely says "unspecified"
    is reported as ``None`` so callers fall back to the type half rather than
    translating a non-answer.
    """
    if not isinstance(value, str):
        return None, None
    type_part, _, purpose_part = value.partition(";")
    type_part = type_part.strip()
    purpose_part = purpose_part.strip()
    if purpose_part.casefold() in _UNSPECIFIED_PURPOSES:
        purpose_part = ""
    return (type_part or None), (purpose_part or None)


def translate_purpose(value) -> str | None:
    """English label for a compound ``andamal`` value.

    Falls back through purpose → type → the raw string, so an unrecognised value
    is passed through rather than silently blanked.
    """
    type_sv, purpose_sv = split_purpose(value)
    if purpose_sv is not None:
        entry = PRIMARY_PURPOSES.get(purpose_sv)
        return entry["en"] if entry else purpose_sv
    if type_sv is not None:
        entry = BUILDING_TYPES.get(type_sv)
        return entry["en"] if entry else type_sv
    return None


def purpose_category(value) -> str:
    """Coarse bucket for a compound ``andamal`` value.

    Prefers the purpose half; falls back to the type half, which is what rescues
    the type-only rows ("Komplementbyggnad;" is 64% of the Helsingborg extract).
    Only a genuinely unrecognised value reaches ``"Other"``.
    """
    type_sv, purpose_sv = split_purpose(value)
    if purpose_sv is not None:
        entry = PRIMARY_PURPOSES.get(purpose_sv)
        if entry:
            return entry["category"]
    if type_sv is not None:
        entry = BUILDING_TYPES.get(type_sv)
        if entry:
            return entry["category"]
    return "Other"


def translate_collection_level(value) -> str | None:
    """English label for ``insamlingslage``.

    The table is keyed lowercase and the data is capitalised, so this casefolds.
    A direct lookup matches nothing at all.
    """
    if not isinstance(value, str):
        return None
    entry = COLLECTION_LEVELS.get(value.strip().casefold())
    return entry["en"] if entry else value


class BuildingsPipeline(BasePipeline):
    """
    Pipeline for the Swedish buildings (Byggnad) dataset.

    Workflow:
      1. Load: Read GeoPackage, preserve raw Swedish field names
      2. Validate: Check geometry, CRS, completeness
      3. Preprocess: Translate fields to English, standardise values
      4. Export: Save processed GeoPackage + snapshot + metadata

    Configuration keys (passed as ``config`` to ``__init__``):

    ``input_gpkg``   — required, path to the raw national Byggnad GeoPackage
    ``input_layer``  — optional layer name; the first layer is used if omitted
    ``postprocess``  — default ``True``; also write the deduplicated snapshot
    ``output_dir``   — read by :meth:`BasePipeline.run`
    """

    def __init__(self, name: str = "Buildings", config: dict = None, verbose: bool = True):
        """Initialise the pipeline with the Swedish buildings lookup tables."""
        super().__init__(name, config, verbose)
        self.field_translations = FIELD_TRANSLATIONS
        self.building_types = BUILDING_TYPES
        self.primary_purposes = PRIMARY_PURPOSES
        # Populated by export(); reported in the run summary.
        self.postprocess_report = {}

    def load(self):
        """Load the raw GeoPackage, preserving Swedish field names."""
        # Required rather than defaulted: the national Byggnad extract is not part
        # of this repository, and a wrong default path fails much later and much
        # less clearly than a missing key does here.
        raw_path = self.config.get("input_gpkg")
        if not raw_path:
            raise ValueError(
                "config['input_gpkg'] is required — the path to the raw "
                "Lantmäteriet Byggnad GeoPackage. It is not shipped with this "
                "repository; see README.md."
            )

        input_path = Path(raw_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input GeoPackage not found: {input_path}")

        layer = self.config.get("input_layer")
        self.logger.info(f"Loading buildings from {input_path}")
        self.data = (
            gpd.read_file(input_path, layer=layer) if layer
            else gpd.read_file(input_path)
        )

        self.logger.info(f"  - Loaded {len(self.data):,} buildings")
        self.logger.info(f"  - Columns: {len(self.data.columns)} fields")
        self.logger.info(f"  - CRS: {self.data.crs}")
        self.logger.info(f"  - Geometry types: {self.data.geometry.type.unique()}")

    def validate(self) -> dict:
        """Validate data quality and structure.

        Collects issues rather than raising: a CRS mismatch or a handful of
        invalid geometries should be visible in the report and in the run log,
        not stop a 2,861-row national extract dead.
        """
        report = {
            "total_buildings": len(self.data),
            "fields": len(self.data.columns),
            "crs": str(self.data.crs),
            "geometry_types": self.data.geometry.type.unique().tolist(),
            "issues": [],
        }

        # Source CRS is SWEREF 99 TM. The reconstruction pipeline reprojects to
        # EPSG:3008 on load (pipeline/io.py), so this checks provenance, not the
        # working CRS.
        if self.data.crs is None:
            report["issues"].append("No CRS on the source layer")
        elif self.data.crs.to_string() != "EPSG:3006":
            report["issues"].append(f"CRS mismatch: expected EPSG:3006, got {self.data.crs}")

        null_geom = self.data.geometry.isnull().sum()
        if null_geom > 0:
            report["issues"].append(f"Null geometries: {null_geom}")

        invalid_geom = (~self.data.geometry.is_valid).sum()
        if invalid_geom > 0:
            report["issues"].append(f"Invalid geometries: {invalid_geom}")

        # Fields the later stages depend on; named in the product description.
        required_fields = ["objektidentitet", "objekttyp", "andamal1"]
        missing_fields = [f for f in required_fields if f not in self.data.columns]
        if missing_fields:
            report["issues"].append(f"Missing required fields: {missing_fields}")

        for field in ["andamal1", "husnummer"]:
            if field in self.data.columns:
                null_count = self.data[field].isna().sum()
                report[f"{field}_null_pct"] = (null_count / len(self.data)) * 100

        self.validation_report = report
        return report

    def preprocess(self):
        """
        Translate Swedish → English and standardise coded values.

        Steps:
        1. Rename fields to English using FIELD_TRANSLATIONS
        2. Translate building type values
        3. Translate and categorise the compound primary purpose
        4. Translate the collection level
        5. Normalise the Ja/Nej flag to a real boolean

        Raw columns are kept alongside the translated ones. Nothing is dropped —
        the English columns are additive, so the original values stay auditable.
        """
        self.logger.info("Translating field names (Swedish → English)")

        rename_map = {
            sv: en for sv, en in self.field_translations.items()
            if sv in self.data.columns
        }
        self.data = self.data.rename(columns=rename_map)
        self.logger.info(f"  - Renamed {len(rename_map)} fields")

        if "object_type" in self.data.columns:
            self.logger.info("Translating building types")
            self.data["object_type_en"] = self.data["object_type"].map(
                lambda x: self.building_types.get(x, {}).get("en", x)
            )
            self.data["object_type_category"] = self.data["object_type"].map(
                lambda x: self.building_types.get(x, {}).get("description", None)
            )

        if "primary_purpose" in self.data.columns:
            self.logger.info("Translating primary purposes")
            self.data["primary_purpose_en"] = self.data["primary_purpose"].map(
                translate_purpose
            )
            self.data["primary_purpose_category"] = self.data["primary_purpose"].map(
                purpose_category
            )

        if "collection_level" in self.data.columns:
            self.logger.info("Translating collection levels")
            self.data["collection_level_en"] = self.data["collection_level"].map(
                translate_collection_level
            )

        if "main_building_flag" in self.data.columns:
            self.data["main_building_flag"] = self.data["main_building_flag"].map(
                {"Ja": True, "Nej": False}
            )

        self.preprocessing_report = {
            "fields_renamed": len(rename_map),
            "columns_after": len(self.data.columns),
        }
        self.logger.info("Preprocessing complete")

    def export(self, output_dir: Path):
        """
        Export the processed dataset, the snapshot, and the metadata.

        Outputs:
        - ``buildings_processed.gpkg``            — all rows, English field names
        - ``buildings_processed_postprocess.gpkg``— newest row per object_id
        - ``buildings_metadata.json``             — translation tables + validation
        - ``buildings_summary.json``              — dataset statistics
        - ``buildings_postprocess_report.{json,md}`` — what the snapshot removed

        The snapshot runs as part of the normal export, not as a separate opt-in
        call. It produces the layer ``config.yml`` actually consumes, so leaving it
        to the caller meant the project's primary input could not be reproduced by
        simply running the pipeline. Set ``config['postprocess'] = False`` to skip.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_gpkg = output_dir / "buildings_processed.gpkg"
        self.logger.info(f"Exporting to {output_gpkg}")
        self.data.to_file(output_gpkg, layer="buildings")

        metadata = {
            "dataset": DATASET_METADATA,
            "field_translations": self.field_translations,
            "building_types": self.building_types,
            "primary_purposes": self.primary_purposes,
            "collection_levels": COLLECTION_LEVELS,
            "validation_report": self.validation_report,
        }

        metadata_file = output_dir / "buildings_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        self.logger.info(f"Exported metadata to {metadata_file}")

        summary = {
            "total_buildings": len(self.data),
            "columns": len(self.data.columns),
            "crs": str(self.data.crs),
            "geometry_valid": (~self.data.geometry.isnull() & self.data.geometry.is_valid).sum(),
            "fields_translated": len(self.field_translations),
        }

        if "object_type_en" in self.data.columns:
            summary["building_types_distribution"] = (
                self.data["object_type_en"].value_counts().to_dict()
            )

        if "primary_purpose_category" in self.data.columns:
            summary["purpose_categories"] = (
                self.data["primary_purpose_category"].value_counts().to_dict()
            )

        # -- deduplicated snapshot ------------------------------------------
        if self.config.get("postprocess", True):
            self.logger.info("Building postprocess snapshot (newest row per object_id)")
            _, self.postprocess_report = build_postprocess_snapshot(
                self.data, output_dir
            )
            summary["postprocess"] = self.postprocess_report
            self.logger.info(
                f"  - {self.postprocess_report['input_rows']:,} in, "
                f"{self.postprocess_report['output_rows']:,} out"
            )
        else:
            self.logger.info("Postprocess snapshot disabled by config")

        summary_file = output_dir / "buildings_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        self.logger.info(f"Exported summary to {summary_file}")
