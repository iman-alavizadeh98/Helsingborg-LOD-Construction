"""
Buildings dataset configuration and translations.

Contains:
- Field name translations (Swedish → English)
- Building type classifications
- Purpose/usage category mappings
- Dataset metadata
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
# Values for objekttyp field (Table 4 in PDF)

BUILDING_TYPES = {
    "Bostad": {
        "en": "Residence",
        "description": "Building used for residential purposes (single/multi-family, >15 kvm)",
        "object_type_nr": 2061
    },
    "Industri": {
        "en": "Industrial",
        "description": "Building containing manufacturing or processing of products (>15 kvm)",
        "object_type_nr": 2062
    },
    "Samhällsfunktion": {
        "en": "Public facility",
        "description": "Building for public community services (>15 kvm)",
        "object_type_nr": 2063
    },
    "Verksamhet": {
        "en": "Business",
        "description": "Building used primarily for business (>50% non-residential, >15 kvm)",
        "object_type_nr": 2064
    },
    "Ekonomibyggnad": {
        "en": "Farm building",
        "description": "Building for agriculture/forestry/similar activities (>15 kvm)",
        "object_type_nr": 2065
    },
    "Komplementbyggnad": {
        "en": "Ancillary building",
        "description": "Small building attached to dwelling (garage, shed, etc., >15 kvm)",
        "object_type_nr": 2066
    },
    "Övrig byggnad": {
        "en": "Other building",
        "description": "Building with other purpose (colonist hut, shelter, tower, etc., >15 kvm)",
        "object_type_nr": 2067
    },
}

# === PRIMARY PURPOSE (ANDAMÅL1) CATEGORIES ===
# From Table 6 in PDF - comprehensive list

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
# Table 7 in PDF - how building location was determined

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
