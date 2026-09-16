# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Iman Alavi Zadeh <iman.alavi98@gmail.com>
#
# Author: Iman Alavi Zadeh
# Developed with AI-assisted (agentic) programming; reviewed by the author.

"""
Buildings dataset lookup tables (Swedish → English).

Contains:
- Field name translations (Swedish → English)
- Building type classifications
- Purpose/usage category mappings
- Collection-level (positional provenance) mappings
- Dataset metadata

Constants only — no I/O, no configuration loading. The project's YAML config
loader is ``pipeline_common/config.py``; this module was once also called ``config.py``
and the collision was a standing source of confusion.

All keys are the *raw Swedish values as they appear in the source GeoPackage*.
Two traps are baked into that data and the lookups below are shaped around them:

* ``andamal1`` is compound, ``"<Type>;<Purpose>"`` — e.g.
  ``"Bostad;Småhus friliggande"``, and often type-only with a trailing semicolon
  (``"Komplementbyggnad;"``). ``PRIMARY_PURPOSES`` is keyed on the *purpose half
  alone*, so callers must split before looking up. ``pipeline.translate_purpose``
  does this.
* ``insamlingslage`` arrives capitalised (``"Fasad"``) while ``COLLECTION_LEVELS``
  is keyed lowercase, so lookups must casefold.
"""

# === FIELD NAME TRANSLATIONS (Swedish → English) ===
# Based on Lantmäteriet PRODUKTBESKRIVNING: Byggnad Nedladdning, vektor (v1.6)

FIELD_TRANSLATIONS = {
    # Core identifiers
    "objektidentitet": "object_id",
    "versiongiltigfran": "version_valid_from",
    "objektversion": "object_version",
    "objekttypnr": "object_type_number",
    "ursprunglig_organisation": "original_organisation",
    
    # Position and accuracy
    "lagesosakerhetplan": "position_uncertainty_plan_m",
    "lagesosakerhethojd": "position_uncertainty_height_m",
    "insamlingslage": "collection_level",
    
    # Classification
    "objekttyp": "object_type",
    "huvudbyggnad": "main_building_flag",
    "husnummer": "house_number",
    
    # Names
    "byggnadsnamn1": "building_name_primary",
    "byggnadsnamn2": "building_name_secondary",
    "byggnadsnamn3": "building_name_tertiary",
    
    # Usage/Purpose (andamål)
    "andamal1": "primary_purpose",
    "andamal2": "secondary_purpose",
    "andamal3": "tertiary_purpose",
    "andamal4": "quaternary_purpose",
    "andamal5": "quinary_purpose",
}

# === BUILDING OBJECT TYPES ===
# Values for the objekttyp field (Table 4 in the product description).
#
# `category` is the coarse bucket also used by PRIMARY_PURPOSES below. It exists
# so that a compound andamal1 value carrying no purpose half — "Komplementbyggnad;"
# and friends, 64% of the Helsingborg extract — can still be categorised from its
# type half instead of falling through to "Other".

BUILDING_TYPES = {
    "Bostad": {
        "en": "Residence",
        "category": "Residence",
        "description": "Building used for residential purposes (single/multi-family, >15 kvm)",
        "object_type_nr": 2061
    },
    "Industri": {
        "en": "Industrial",
        "category": "Industrial",
        "description": "Building containing manufacturing or processing of products (>15 kvm)",
        "object_type_nr": 2062
    },
    "Samhällsfunktion": {
        "en": "Public facility",
        "category": "Public",
        "description": "Building for public community services (>15 kvm)",
        "object_type_nr": 2063
    },
    "Verksamhet": {
        "en": "Business",
        "category": "Business",
        "description": "Building used primarily for business (>50% non-residential, >15 kvm)",
        "object_type_nr": 2064
    },
    "Ekonomibyggnad": {
        "en": "Farm building",
        "category": "Farm",
        "description": "Building for agriculture/forestry/similar activities (>15 kvm)",
        "object_type_nr": 2065
    },
    "Komplementbyggnad": {
        "en": "Ancillary building",
        "category": "Ancillary",
        "description": "Small building attached to dwelling (garage, shed, etc., >15 kvm)",
        "object_type_nr": 2066
    },
    "Övrig byggnad": {
        "en": "Other building",
        "category": "Other",
        "description": "Building with other purpose (colonist hut, shelter, tower, etc., >15 kvm)",
        "object_type_nr": 2067
    },
}

# === PRIMARY PURPOSE (ANDAMÅL1) CATEGORIES ===
# From Table 6 in the product description.
#
# Keyed on the *purpose half only*. The raw column holds "<Type>;<Purpose>", so a
# direct lookup against the raw value never matches — that was a real bug: every
# row in the Helsingborg extract came out untranslated and categorised "Other".
# Split first; `pipeline.translate_purpose` is the supported way in.
#
# Not exhaustive. Table 6 lists more purposes than appear in this region, and the
# Verksamhet / Ekonomibyggnad / Komplementbyggnad / Övrig byggnad types have no
# purpose entries at all — which is exactly why the BUILDING_TYPES fallback above
# matters rather than being a nicety.

PRIMARY_PURPOSES = {
    # Bostad (Residence)
    "Småhus friliggande": {"en": "Single-family detached house", "category": "Residence"},
    "Småhus kedjehus": {"en": "Townhouse/chain house", "category": "Residence"},
    "Småhus radhus": {"en": "Row house", "category": "Residence"},
    "Småhus med flera lägenheter": {"en": "Multi-unit small building", "category": "Residence"},
    "Flerfamiljshus": {"en": "Multi-family apartment building", "category": "Residence"},
    
    # Industri (Industrial)
    "Annan tillverkningsindustri": {"en": "Other manufacturing", "category": "Industrial"},
    "Industrihotell": {"en": "Industrial complex", "category": "Industrial"},
    "Metall- eller maskinindustri": {"en": "Metal/machinery manufacturing", "category": "Industrial"},
    "Textilindustri": {"en": "Textile industry", "category": "Industrial"},
    "Trävaruindustri": {"en": "Wood products industry", "category": "Industrial"},
    
    # Samhällsfunktion (Public facility) - extensive list
    "Badhus": {"en": "Public bath", "category": "Public"},
    "Brandstation": {"en": "Fire station", "category": "Public"},
    "Busstation": {"en": "Bus station", "category": "Public"},
    "Djursjukhus": {"en": "Veterinary hospital", "category": "Public"},
    "Högskola": {"en": "University/College", "category": "Public"},
    "Ishall": {"en": "Ice hockey rink", "category": "Public"},
    "Järnvägsstation": {"en": "Railway station", "category": "Public"},
    "Kommunhus": {"en": "Municipal building", "category": "Public"},
    "Kriminalvårdsanstalt": {"en": "Prison", "category": "Public"},
    "Kulturbyggnad": {"en": "Cultural building", "category": "Public"},
    "Multiarena": {"en": "Multi-purpose arena", "category": "Public"},
    "Polisstation": {"en": "Police station", "category": "Public"},
    "Ridhus": {"en": "Riding hall", "category": "Public"},
    "Samfund": {"en": "Religious assembly hall", "category": "Public"},
    "Sjukhus": {"en": "Hospital", "category": "Public"},
    "Skola": {"en": "School", "category": "Public"},
    "Sporthall": {"en": "Sports hall", "category": "Public"},
    "Universitet": {"en": "University", "category": "Public"},
    "Vårdcentral": {"en": "Health center", "category": "Public"},
}

# === COLLECTION LEVEL (INSAMLINGSLAGE) ===
# Table 7 in the product description — how the building outline was determined.
#
# This matters more than it looks for LOD2.2. "Fasad" means the outline was
# measured at the facade, *inside* the roof edge, so those polygons need the
# roofprint buffer that Phase 1 calibrates; "Takkant" polygons are already at the
# roof edge and need little or none.
#
# Keys are lowercase; the source data is capitalised ("Fasad"). Look up with
# .casefold() — a direct lookup silently no-ops, which it did until this was fixed.

COLLECTION_LEVELS = {
    "fasad": {
        "en": "Facade",
        "description": "Building perimeter measured from facade within roof edge"
    },
    "takkant": {
        "en": "Roof edge",
        "description": "Building boundary measured at roof edge line"
    },
    "illustrativt läge": {
        "en": "Schematic/illustrative",
        "description": "Building shown schematically, not surveyed (may be under road/structure)"
    },
    "ospecificerad": {
        "en": "Unspecified",
        "description": "Collection level not specified"
    },
}

# === DATASET METADATA ===

DATASET_METADATA = {
    "name_sv": "Byggnad, vektor",
    "name_en": "Buildings, vector",
    "authority": "Lantmäteriet (Swedish Land Survey)",
    "version": "1.6",
    "date": "2023-02-01",
    "coordinate_system_plan": "SWEREF 99 TM",
    "coordinate_system_height": "RH 2000",
    "geographic_coverage": "Sweden (nationwide)",
    "minimum_size_m2": 15.0,
    "description": "Vector dataset of building footprints with semantic attributes including type, usage, and positional accuracy",
    "update_frequency": "Continuous within municipal responsibility areas, periodic outside",
    "data_quality": {
        "completeness": "~96% (4% discrepancies in surveyed areas)",
        "logical_consistency": "High - strict geometric and topological validation",
        "thematic_accuracy": "High - standardized building classifications",
        "positional_accuracy_plan_m": (0.02, 50.0),  # Range: 0.02-50 meters
    }
}
