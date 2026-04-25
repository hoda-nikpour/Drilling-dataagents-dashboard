from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make root-level modules importable:
# config.py, app.py, agents/, utils/, etc.
sys.path.insert(0, str(PROJECT_ROOT))

# Temporary compatibility layer for files that still use old-style imports,
# for example: from activity_support import ...
PACKAGE_DIRS = [
    "agents",
    "utils",
    "data_access",
    "services",
    "ui",
    "visualization",
]

for folder in PACKAGE_DIRS:
    path = PROJECT_ROOT / folder
    if path.exists():
        sys.path.insert(0, str(path))