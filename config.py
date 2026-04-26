from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# Dashboard settings
N_TRACKS = 4
MAX_PARAMS_PER_TRACK = 3

# Performance tuning
MAX_POINTS_PER_TRACE = 12000
MAX_POINTS_PER_TRACE_ZOOM = 20000

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

PARAMETER_ALIASES = {
    "Bit Depth": ["BDTI", "BITD", "BIT_DEPTH"],
    "Well Depth": ["GS_DMEA", "DMEA", "DEPT", "GS_DVER", "DVER", "DBTV", "GS_DBTM", "DBTM"],
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
    "HKL": ["GS_HKLD", "HKL", "HKLD"],
    "MFI": ["GS_MFI", "MFI"],
    "SPP": ["GS_SPPA", "SPP", "SPPA"],
    "RPMB": ["RPMB", "GS_RPM", "RPM"],
    "TRQ": ["GS_TQA", "TRQ", "TQA"],
    "ROP": ["ROP", "GS_ROP", "DRILL_RATE", "RATE_OF_PENETRATION"],
    "Pit Level": ["GS_PITLV", "GS_PITLVL", "GS_PIT", "PITLV", "PITLVL", "PIT"],
    "WOB": ["WOB", "GS_WOB", "SWOB", "GS_SWOB", "SWOB30s"],
}

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
        "logical_min": -5.0,
        "logical_max": 60.0,
    },
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
    "PSpike": "rgba(41, 128, 185, 0.92)",
    "OverPull": "rgba(39, 174, 96, 0.92)",
    "TookWeight": "rgba(243, 156, 18, 0.92)",
}