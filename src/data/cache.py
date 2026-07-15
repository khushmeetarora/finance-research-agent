"""Tiny on-disk JSON cache with TTL.

Keeps the data layer offline-friendly and avoids hammering free APIs.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..config import cache_dir


def _key_to_path(namespace: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]
    folder = cache_dir() / namespace
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def get(namespace: str, key: str, ttl_seconds: int) -> Any | None:
    """Return cached value or None if missing/expired."""
    path = _key_to_path(namespace, key)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - payload.get("_ts", 0) > ttl_seconds:
        return None
    return payload.get("value")


def put(namespace: str, key: str, value: Any) -> None:
    path = _key_to_path(namespace, key)
    payload = {"_ts": time.time(), "value": value}
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, default=str)
    tmp.replace(path)
