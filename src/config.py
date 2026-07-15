"""Profile loading + global config helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "config" / "profiles"
DEFAULT_CACHE_DIR = REPO_ROOT / ".fra_cache"
DEFAULT_MEMORY_DIR = REPO_ROOT / ".fra_memory"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"


def load_profile(profile_id: str) -> dict[str, Any]:
    """Load a profile YAML by id (e.g. 'india_adult')."""
    path = PROFILES_DIR / f"{profile_id}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"Profile {profile_id!r} not found at {path}. "
            f"Available: {available}"
        )
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cache_dir() -> Path:
    override = os.environ.get("FRA_CACHE_DIR")
    path = Path(override) if override else DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_dir() -> Path:
    DEFAULT_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_MEMORY_DIR


def reports_dir() -> Path:
    DEFAULT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_REPORTS_DIR
