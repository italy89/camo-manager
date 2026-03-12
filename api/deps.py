"""
Shared dependencies for the FastAPI backend.
- Singleton BrowserManager instance
- Imports from parent directory: manager.py and browser_manager_v3.py
"""

import sys
from pathlib import Path

# Add parent directory (camo-manager root) to sys.path so we can import
# manager.py and browser_manager_v3.py
_PARENT_DIR = Path(__file__).resolve().parent.parent
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

# Re-export everything we need from the existing modules
import manager  # noqa: E402
from browser_manager_v3 import BrowserManager, BrowserError  # noqa: E402

# Singleton BrowserManager — shared across all routes
browser_manager = BrowserManager()

# Re-export manager constants for convenience
PROFILES_DIR = manager.PROFILES_DIR
BASE_DIR = manager.BASE_DIR
