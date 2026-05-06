from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# Dashboard settings
N_TRACKS = 4
MAX_PARAMS_PER_TRACK = 3

# Performance tuning
MAX_POINTS_PER_TRACE = 30000
MAX_POINTS_PER_TRACE_ZOOM = 60000

# Marker settings
# Default dashboard view should be clean lines without dots.
BASE_MARKER_SIZE = 2.0
ZOOM_MARKER_SIZE = 4.0

MARKER_DISPLAY_OPTIONS = [
    "Lines only",
    "Small dots",
    "Larger dots",
]

DEFAULT_MARKER_DISPLAY = "Lines only"

# Metadata columns required for the app
REQUIRED_META_COLUMNS = ["TIME", "_section_in", "DEPT"]

# Track colors
TRACK_COLOR_PALETTE = [
    "#8E44AD",
    "#3498DB",
    "#E74C3C",
]

# ------------------------------------------------------------
# Parameter aliases
# ------------------------------------------------------------
# Important:
# Do NOT use BDTI as Bit Depth in these datasets.
# In the catalog, BDTI appears with unit "h" in several wells/sections.
# The bit-depth/depth-of-bit curve is DBTM / GS_DBTM.
#
# Well Depth / Hole Depth is DMEA / GS_DMEA / DEPT.
# Bit Depth is DBTM / GS_DBTM.
# ------------------------------------------------------------

GLOBAL_PARAMETER_ALIASES = {
    "Bit Depth": ["GS_DBTM", "DBTM", "BITD", "BIT_DEPTH"],
    "Well Depth": ["GS_DMEA", "DMEA", "DEPT", "GS_DVER", "DVER"],
    "Casing Depth": [
        "DepthCsg",
        "DEPTH_CSG",
        "CSG_DEPTH",
        "CASING_DEPTH",
        "Depth Casing",
        "DEPTH_CASING",
        "DCAS",
    ],
    "Mud Motor On": [
        "MudMotorOn",
        "MUD_MOTOR_ON",
        "MOTOR_ON",
        "MMOTOR",
        "GS_MUD_MOTOR_ON",
    ],
    "BPOS": ["GS_BPOS", "BPOS"],
    "HKL": ["GS_HKLD", "HKLD", "HKLD30s", "HKL"],
    "MFI": ["GS_TFLO", "TFLO", "TFLO30s", "GS_CFIA", "MFI"],
    "SPP": ["GS_SPPA", "SPPA", "SIG_SPP5s", "SPP"],
    "RPMB": ["GS_RPM", "RPM", "RPMB", "RPM30s"],
    "TRQ": ["GS_TQA", "TQA", "SIG_TQ30s", "TRQ"],
    "ROP": ["GS_ROP", "ROP", "ROP5", "ROP30s", "DRILL_RATE", "RATE_OF_PENETRATION"],
    "Pit Level": ["GS_PITLV", "GS_PITLVL", "GS_PIT", "PITLV", "PITLVL", "PIT"],
    "WOB": ["GS_SWOB", "SWOB", "SWOB30s", "WOB"],
}


WELL_PARAMETER_ALIASES = {
    # --------------------------------------------------------
    # 34-10-C47
    # Older compact mnemonic format.
    # --------------------------------------------------------
    "34-10-C47": {
        "Bit Depth": ["DBTM", "DBTV"],
        "Well Depth": ["DMEA", "DVER", "DEPT"],
        "BPOS": ["BPOS"],
        "HKL": ["HKL"],
        "MFI": ["MFI"],
        "SPP": ["SPP"],
        "RPMB": ["RPMB", "RPMA"],
        "TRQ": ["TRQ"],
        "ROP": ["ROP"],
        "WOB": ["WOB"],
    },

    # --------------------------------------------------------
    # F-10
    # WITSML-style mixed format.
    # Prefer GS_* curves where they are the cleaned surface channels.
    # --------------------------------------------------------
    "F-10": {
        "Bit Depth": ["GS_DBTM", "DBTM"],
        "Well Depth": ["GS_DMEA", "DMEA", "DEPT", "GS_DVER", "DVER"],
        "BPOS": ["GS_BPOS", "BPOS"],
        "HKL": ["GS_HKLD", "HKLD", "HKLD30s", "HKLX", "HKLI", "HKLO", "HKLN"],
        "MFI": ["GS_TFLO", "TFLO", "TFLO30s", "GS_CFIA"],
        "SPP": ["GS_SPPA", "SPPA", "SIG_SPP5s", "APRS_RT", "APRS_P", "GS_CHKP"],
        "RPMB": ["GS_RPM", "RPM", "RPM30s", "DRPM", "DRPM30s", "CRPM_RT"],
        "TRQ": ["GS_TQA", "TQA", "SIG_TQ30s"],
        "ROP": ["GS_ROP", "ROP", "ROP5", "ROP30s", "QROP"],
        "WOB": ["GS_SWOB", "SWOB", "SWOB30s"],
    },

    # --------------------------------------------------------
    # F-15
    # Similar WITSML-style mixed format.
    # --------------------------------------------------------
    "F-15": {
        "Bit Depth": ["GS_DBTM", "DBTM"],
        "Well Depth": ["GS_DMEA", "DMEA", "DEPT", "GS_DVER", "DVER"],
        "BPOS": ["GS_BPOS", "BPOS"],
        "HKL": ["GS_HKLD", "HKLD", "HKLD30s", "HKLX", "HKLI", "HKLO", "HKLN"],
        "MFI": ["GS_TFLO", "TFLO", "TFLO30s", "GS_CFIA"],
        "SPP": ["GS_SPPA", "SPPA", "SIG_SPP5s", "APRS_RT", "APRS_P", "GS_CHKP"],
        "RPMB": ["GS_RPM", "RPM", "RPM30s", "DRPM", "DRPM30s", "CRPM_RT"],
        "TRQ": ["GS_TQA", "TQA", "SIG_TQ30s"],
        "ROP": ["GS_ROP", "ROP", "ROP5", "ROP30s", "QROP"],
        "WOB": ["GS_SWOB", "SWOB", "SWOB30s"],
    },
}


# Optional section-specific overrides.
# Use this only when one section is known to need a different priority.
SECTION_PARAMETER_ALIASES = {
    # Example structure:
    # ("F-10", "8.5"): {
    #     "Well Depth": ["DMEA", "GS_DMEA", "DEPT"],
    # }
}


# Backward-compatible name used by existing imports.
PARAMETER_ALIASES = GLOBAL_PARAMETER_ALIASES

PARAMETER_DISPLAY_NAMES = {
    "Bit Depth": "Bit Depth — current bit depth",
    "Well Depth": "Well Depth — measured/hole depth",
    "Casing Depth": "Casing Depth — casing shoe / last casing depth",
    "Mud Motor On": "Mud Motor On — motor status flag",
    "BPOS": "BPOS — block position",
    "HKL": "HKL — hook load",
    "MFI": "MFI — mud flow in",
    "SPP": "SPP — standpipe pressure",
    "RPMB": "RPMB — rotary speed",
    "TRQ": "TRQ — torque",
    "ROP": "ROP — rate of penetration",
    "Pit Level": "Pit Level — mud pit level",
    "WOB": "WOB — weight on bit",
}

PARAMETER_CATALOG = {
    "Bit Depth": {
        "meaning": "Current bit depth",
        "unit": "m",
        "logical_min": 0.0,
        "logical_max": 6000.0,
    },
    "Well Depth": {
        "meaning": "Measured/hole depth",
        "unit": "m",
        "logical_min": 0.0,
        "logical_max": 6000.0,
    },
    "Casing Depth": {
        "meaning": "Casing shoe depth / last casing depth used for open-hole length",
        "unit": "m",
        "logical_min": 0.0,
        "logical_max": 6000.0,
    },
    "Mud Motor On": {
        "meaning": "Mud motor status flag",
        "unit": "0/1",
        "logical_min": 0.0,
        "logical_max": 1.0,
    },
    "BPOS": {
        "meaning": "Block position",
        "unit": "m",
        "logical_min": 0.0,
        "logical_max": 50.0,
    },
    "HKL": {
        "meaning": "Hook load",
        "unit": "t or kkgf",
        "logical_min": 0.0,
        "logical_max": 250.0,
    },
    "MFI": {
        "meaning": "Mud flow in",
        "unit": "l/min",
        "logical_min": 0.0,
        "logical_max": 4000.0,
    },
    "SPP": {
        "meaning": "Standpipe pressure",
        "unit": "kPa",
        "logical_min": 0.0,
        "logical_max": 4000.0,
    },
    "RPMB": {
        "meaning": "Rotary speed",
        "unit": "rpm",
        "logical_min": 0.0,
        "logical_max": 250.0,
    },
    "TRQ": {
        "meaning": "Torque",
        "unit": "kN.m",
        "logical_min": 0.0,
        "logical_max": 40.0,
    },
    "ROP": {
        "meaning": "Rate of penetration",
        "unit": "m/h",
        "logical_min": 0.0,
        "logical_max": 200.0,
    },
    "Pit Level": {
        "meaning": "Mud pit level",
        "unit": "level / volume unit",
        "logical_min": 0.0,
        "logical_max": 100.0,
    },
    "WOB": {
        "meaning": "Weight on bit",
        "unit": "ton",
        "logical_min": 0.0,
        "logical_max": 60.0,
    },
}

# ------------------------------------------------------------
# Data cleaning rules
# ------------------------------------------------------------
# PARAMETER_CATALOG is for display ranges.
# CLEANING_RULES is for impossible values, zero drift, and agent trust.
#
# Raw columns are never overwritten.
# The dashboard creates extra columns:
#   <raw_col>__clean
#   <raw_col>__quality
# ------------------------------------------------------------

CLEANING_RULES = {
    "Bit Depth": {
        "hard_min": 0.0,
        "hard_max": 50000.0,
    },
    "Well Depth": {
        "hard_min": 0.0,
        "hard_max": 50000.0,
    },
    "Casing Depth": {
        "hard_min": 0.0,
        "hard_max": 50000.0,
    },
    "BPOS": {
        "hard_min": 0.0,
        "hard_max": 500.0,
    },
    "HKL": {
        "hard_min": -5.0,
        "hard_max": 500.0,
        "zero_drift_min": -5.0,
        "clip_small_negative_to_zero": True,
    },
    "MFI": {
        "hard_min": -10.0,
        "hard_max": 20000.0,
        "zero_drift_min": -10.0,
        "clip_small_negative_to_zero": True,
    },
    "SPP": {
        "hard_min": -10.0,
        "hard_max": 10000.0,
        "zero_drift_min": -10.0,
        "clip_small_negative_to_zero": True,
    },
    "RPMB": {
        "hard_min": -2.0,
        "hard_max": 500.0,
        "zero_drift_min": -2.0,
        "clip_small_negative_to_zero": True,
    },
    "TRQ": {
        "hard_min": -2.0,
        "hard_max": 200.0,
        "zero_drift_min": -2.0,
        "clip_small_negative_to_zero": True,
    },
    "ROP": {
        "hard_min": -5.0,
        "hard_max": 2000.0,
        "zero_drift_min": -5.0,
        "clip_small_negative_to_zero": True,
    },
    "Pit Level": {
        "hard_min": 0.0,
        "hard_max": 1000.0,
    },
    "WOB": {
        "hard_min": -1.0,
        "hard_max": 120.0,
        "zero_drift_min": -1.0,
        "clip_small_negative_to_zero": True,
    },
    "Mud Motor On": {
        "hard_min": 0.0,
        "hard_max": 1.0,
    },
}


# Well-specific cleaning overrides.
# These are intentionally more tolerant than PARAMETER_CATALOG display ranges.
WELL_CLEANING_RULES = {
    "34-10-C47": {
        "BPOS": {
            "hard_min": 0.0,
            "hard_max": 60.0,
        },
        "HKL": {
            "hard_min": -5.0,
            "hard_max": 400.0,
            "zero_drift_min": -5.0,
            "clip_small_negative_to_zero": True,
        },
        "MFI": {
            "hard_min": -10.0,
            "hard_max": 6000.0,
            "zero_drift_min": -10.0,
            "clip_small_negative_to_zero": True,
        },
        "SPP": {
            "hard_min": -10.0,
            "hard_max": 10000.0,
            "zero_drift_min": -10.0,
            "clip_small_negative_to_zero": True,
        },
        "TRQ": {
            "hard_min": -2.0,
            "hard_max": 150.0,
            "zero_drift_min": -2.0,
            "clip_small_negative_to_zero": True,
        },
        "WOB": {
            "hard_min": -1.0,
            "hard_max": 120.0,
            "zero_drift_min": -1.0,
            "clip_small_negative_to_zero": True,
        },
    },

    "F-10": {
        "BPOS": {
            "hard_min": 0.0,
            "hard_max": 500.0,
        },
        "HKL": {
            "hard_min": -5.0,
            "hard_max": 500.0,
            "zero_drift_min": -5.0,
            "clip_small_negative_to_zero": True,
        },
        "MFI": {
            "hard_min": -10.0,
            "hard_max": 20000.0,
            "zero_drift_min": -10.0,
            "clip_small_negative_to_zero": True,
        },
    },

    "F-15": {
        "BPOS": {
            "hard_min": 0.0,
            "hard_max": 500.0,
        },
        "HKL": {
            "hard_min": -5.0,
            "hard_max": 500.0,
            "zero_drift_min": -5.0,
            "clip_small_negative_to_zero": True,
        },
        "MFI": {
            "hard_min": -10.0,
            "hard_max": 20000.0,
            "zero_drift_min": -10.0,
            "clip_small_negative_to_zero": True,
        },
    },
}


# Optional section-specific overrides.
# These are applied after well-specific rules.
SECTION_CLEANING_RULES = {
    # Example:
    # ("34-10-C47", "8.5"): {
    #     "BPOS": {
    #         "hard_min": 0.0,
    #         "hard_max": 60.0,
    #     },
    # }
}

LOGICAL_PARAMETER_RANGES = {
    label: (meta["logical_min"], meta["logical_max"])
    for label, meta in PARAMETER_CATALOG.items()
}

AGENT_TRACK_XRANGE = (0.0, 1.0)

ACTIVITY_COLOR_MAP = {
    "MakingConnection": "rgba(155, 89, 182, 0.92)",
    "Drilling": "rgba(231, 76, 60, 0.92)",
    "Reaming": "rgba(52, 152, 219, 0.92)",
    "TrippingIn": "rgba(46, 204, 113, 0.92)",
    "TrippingOut": "rgba(241, 196, 15, 0.92)",
    "Conditioning": "rgba(26, 188, 156, 0.92)",
    "Circulating": "rgba(230, 126, 34, 0.92)",
    "Other": "rgba(149, 165, 166, 0.88)",
}

SYMPTOM_COLOR_MAP = {
    "OpenHoleLength": "rgba(142, 68, 173, 0.92)",
    "TRQSpike": "rgba(192, 57, 43, 0.92)",
    "TRQErratic": "rgba(127, 0, 0, 0.92)",
    "PSpike": "rgba(41, 128, 185, 0.92)",
    "OverPull": "rgba(39, 174, 96, 0.92)",
    "TookWeight": "rgba(243, 156, 18, 0.92)",
}