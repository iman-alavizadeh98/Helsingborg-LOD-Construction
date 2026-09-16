"""
Base pipeline class for all data processing pipelines.

Provides abstract interface that all dataset pipelines inherit from.
Ensures consistent structure across different data workflows.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import logging
from datetime import datetime


class BasePipeline(ABC):
    """
    Abstract base class for data processing pipelines.
    
    All dataset-specific pipelines should inherit from this class
    and implement the required methods.
    
    Workflow: load() → validate() → preprocess() → export()
    """
    
    def __init__(self, name: str, config: dict = None, verbose: bool = True):
        """
        Initialize pipeline.
        
        Args:
            name: Human-readable name (e.g., "Byggnad", "Population")
            config: Configuration dictionary with paths and parameters
            verbose: Enable detailed logging
        """
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(name)
        self.data = None  # Will hold loaded data (GeoDataFrame, DataFrame, etc.)
        self.validation_report = {}
        self.preprocessing_report = {}
        
        if verbose:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
            )
    
    @abstractmethod
    def load(self):
        """
        Load raw data from source.
        
        Must populate self.data with loaded data.
        Should preserve raw data without modifications.
        """
        pass
    
    @abstractmethod
    def validate(self) -> dict:
        """
        Validate data quality and structure.
        
        Returns:
            dict with validation metrics and issues
        """
        pass
    
    @abstractmethod
    def preprocess(self):
        """
        Clean, transform, and normalize data.
        
        Modifies self.data in place.
        """
        pass
    
    @abstractmethod
    def export(self, output_dir: Path):
        """
        Save processed data to output directory.
        
        Args:
            output_dir: Path to output directory
        """
        pass
    
    def run(self, output_dir: Path = None) -> dict:
        """
        Execute complete pipeline: load → validate → preprocess → export.
        
        Args:
            output_dir: Optional output directory (uses config if not provided)
        
        Returns:
            dict with pipeline execution summary
        """
        if output_dir is None:
            output_dir = Path(self.config.get("output_dir", "Processed_data"))
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("=" * 80)
        self.logger.info(f"STARTING {self.name.upper()} PIPELINE")
        self.logger.info("=" * 80)
        
        try:
            # Step 1: Load
            self.logger.info(f"\n[1/4] Loading data...")
            self.load()
            self.logger.info(f"✓ Data loaded: {self._describe_data()}")
            
            # Step 2: Validate
            self.logger.info(f"\n[2/4] Validating data...")
            self.validation_report = self.validate()
            self.logger.info(f"✓ Validation complete")
            
            # Step 3: Preprocess
            self.logger.info(f"\n[3/4] Preprocessing data...")
            self.preprocess()
            self.logger.info(f"✓ Preprocessing complete: {self._describe_data()}")
            
            # Step 4: Export
            self.logger.info(f"\n[4/4] Exporting data to {output_dir}...")
            self.export(output_dir)
            self.logger.info(f"✓ Export complete")
            
            # Summary
            summary = {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "pipeline": self.name,
                "output_directory": str(output_dir),
                "validation_report": self.validation_report,
                "preprocessing_report": self.preprocessing_report
            }
            
            self.logger.info("\n" + "=" * 80)
            self.logger.info(f"✓ {self.name.upper()} PIPELINE COMPLETE")
            self.logger.info("=" * 80)
            
            return summary
        
        except Exception as e:
            self.logger.exception(f"Pipeline failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "pipeline": self.name
            }
    
    def _describe_data(self) -> str:
        """Get brief description of current data."""
        if self.data is None:
            return "No data loaded"
        
        try:
            if hasattr(self.data, 'shape'):
                return f"{self.data.shape[0]:,} rows × {self.data.shape[1]} columns"
            else:
                return f"{len(self.data)} items"
        except:
            return "Data loaded (size unknown)"
