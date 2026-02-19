"""
Iris version — single source of truth is /iris-v3/VERSION
"""
from pathlib import Path

_version_file = Path(__file__).resolve().parent.parent / "VERSION"
__version__ = _version_file.read_text().strip() if _version_file.exists() else "unknown"
