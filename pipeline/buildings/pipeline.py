"""
Buildings dataset pipeline.

Loads, validates, analyzes, and preprocesses Swedish building (Byggnad) data.
Implements BasePipeline pattern for reusability with similar datasets.
"""

from pathlib import Path
import geopandas as gpd
import pandas as pd
import logging
from typing import Dict, Any
import json
import numpy as np

from pipelines.base import BasePipeline
from .config import (
    FIELD_TRANSLATIONS,
    BUILDING_TYPES,
    PRIMARY_PURPOSES,
    COLLECTION_LEVELS,
    DATASET_METADATA,
)

logger = logging.getLogger(__name__)


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle numpy/pandas types."""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class BuildingsPipeline(BasePipeline):
    """
    Pipeline for Swedish buildings (Byggnad) dataset.
    
    Workflow:
      1. Load: Read GeoPackage, preserve raw Swedish field names
      2. Validate: Check geometry, CRS, completeness
      3. Preprocess: Translate fields to English, standardize values
      4. Export: Save processed GeoPackage + metadata
    """
    
    def __init__(self, name: str = "Buildings", config: dict = None, verbose: bool = True):
        """Initialize pipeline with Swedish buildings configuration."""
        super().__init__(name, config, verbose)
        self.field_translations = FIELD_TRANSLATIONS
        self.building_types = BUILDING_TYPES
        self.primary_purposes = PRIMARY_PURPOSES
    
    def load(self):
        """Load raw GeoPackage preserving Swedish field names."""
        input_path = Path(self.config.get("input_gpkg", "Raw_data/byggnad_gpkg/byggnad_sverige.gpkg"))
        
        if not input_path.exists():
            raise FileNotFoundError(f"Input GeoPackage not found: {input_path}")
        
        self.logger.info(f"Loading buildings from {input_path}")
        self.data = gpd.read_file(input_path)
        
        self.logger.info(f"  - Loaded {len(self.data):,} buildings")
        self.logger.info(f"  - Columns: {len(self.data.columns)} fields")
        self.logger.info(f"  - CRS: {self.data.crs}")
        self.logger.info(f"  - Geometry types: {self.data.geometry.type.unique()}")
    
    def validate(self) -> dict:
        """Validate data quality and structure."""
        report = {
            "total_buildings": len(self.data),
            "fields": len(self.data.columns),
            "crs": str(self.data.crs),
            "geometry_types": self.data.geometry.type.unique().tolist(),
            "issues": [],
        }
        
        # Check CRS
        if self.data.crs.to_string() != "EPSG:3006":
            report["issues"].append(f"CRS mismatch: expected EPSG:3006, got {self.data.crs}")
        
        # Check null geometries
        null_geom = self.data.geometry.isnull().sum()
        if null_geom > 0:
            report["issues"].append(f"Null geometries: {null_geom}")
        
        # Check invalid geometries
        invalid_geom = (~self.data.geometry.is_valid).sum()
        if invalid_geom > 0:
            report["issues"].append(f"Invalid geometries: {invalid_geom}")
        
        # Check required fields (from PDF)
        required_fields = ["objektidentitet", "objekttyp", "andamal1"]
        missing_fields = [f for f in required_fields if f not in self.data.columns]
        if missing_fields:
            report["issues"].append(f"Missing required fields: {missing_fields}")
        
        # Check field coverage
        for field in ["andamal1", "husnummer"]:
            if field in self.data.columns:
                null_count = self.data[field].isna().sum()
                null_pct = (null_count / len(self.data)) * 100
                report[f"{field}_null_pct"] = null_pct
        
        self.validation_report = report
        return report
    
    def preprocess(self):
        """
        Translate Swedish → English and standardize.
        
        Steps:
        1. Rename fields to English using translations
        2. Translate building type values
        3. Standardize purpose categories
        4. Clean and validate
        """
        self.logger.info("Translating field names (Swedish → English)")
        
        # Rename fields that have translations
        rename_map = {}
        for sv_field, en_field in self.field_translations.items():
            if sv_field in self.data.columns:
                rename_map[sv_field] = en_field
        
        self.data = self.data.rename(columns=rename_map)
        self.logger.info(f"  - Renamed {len(rename_map)} fields")
        
        # Translate object_type values (Bostad → Residence, etc.)
        if "object_type" in self.data.columns:
            self.logger.info("Translating building types")
            self.data["object_type_en"] = self.data["object_type"].map(
                lambda x: self.building_types.get(x, {}).get("en", x)
            )
            self.data["object_type_category"] = self.data["object_type"].map(
                lambda x: self.building_types.get(x, {}).get("description", None)
            )
        
        # Translate primary purpose values
        if "primary_purpose" in self.data.columns:
            self.logger.info("Translating primary purposes")
            self.data["primary_purpose_en"] = self.data["primary_purpose"].map(
                lambda x: self.primary_purposes.get(x, {}).get("en", x)
            )
            self.data["primary_purpose_category"] = self.data["primary_purpose"].map(
                lambda x: self.primary_purposes.get(x, {}).get("category", "Other")
            )
        
        # Translate collection level
        if "collection_level" in self.data.columns:
            self.logger.info("Translating collection levels")
            self.data["collection_level_en"] = self.data["collection_level"].map(
                lambda x: COLLECTION_LEVELS.get(x, {}).get("en", x)
            )
        
        # Standardize boolean fields
        if "main_building_flag" in self.data.columns:
            self.data["main_building_flag"] = self.data["main_building_flag"].map(
                {"Ja": True, "Nej": False}
            )
        
        self.logger.info("Preprocessing complete")
    
    def export(self, output_dir: Path):
        """
        Export processed dataset with metadata.
        
        Outputs:
        - GeoPackage: processed buildings with English field names
        - Metadata JSON: translation mappings and dataset info
        - Summary JSON: statistics about the processed dataset
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Export GeoPackage
        output_gpkg = output_dir / "buildings_processed.gpkg"
        self.logger.info(f"Exporting to {output_gpkg}")
        self.data.to_file(output_gpkg, layer="buildings")
        
        # Export metadata
        metadata = {
            "dataset": DATASET_METADATA,
            "field_translations": self.field_translations,
            "building_types": {k: v for k, v in self.building_types.items()},
            "primary_purposes": {k: v for k, v in self.primary_purposes.items()},
            "collection_levels": {k: v for k, v in COLLECTION_LEVELS.items()},
            "validation_report": self.validation_report,
        }
        
        metadata_file = output_dir / "buildings_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        self.logger.info(f"Exported metadata to {metadata_file}")
        
        # Export summary statistics
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
        
        summary_file = output_dir / "buildings_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        self.logger.info(f"Exported summary to {summary_file}")
