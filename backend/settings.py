# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import os
from typing import Any, Dict

APP_NAME = "SI12"
APP_VERSION = "SI12v1"
MAX_MASSIQUES = 12

CONFIG_DIR = r"C:\tag_massique"
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
TAGS_FILE = os.path.join(CONFIG_DIR, "tags_config.json")


def ensure_dir() -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_json(path: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ensure_dir()
    if not os.path.exists(path):
        return default or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default or {}


def save_json(path: str, data: Dict[str, Any]) -> None:
    ensure_dir()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def load_settings() -> Dict[str, Any]:
    return load_json(CONFIG_FILE, default={"theme": "light"})


def save_settings(data: Dict[str, Any]) -> None:
    save_json(CONFIG_FILE, data)


def load_tags() -> list[str]:
    """
    Retourne 12 tags (8 chars), par défaut MFC00001.. etc.
    """
    data = load_json(TAGS_FILE, default={})
    tags = data.get("tags")
    if isinstance(tags, list) and len(tags) == MAX_MASSIQUES:
        return [str(t)[:8].ljust(8, "_") for t in tags]

    # défaut
    return [f"MFC{i+1:05d}"[:8].ljust(8, "_") for i in range(MAX_MASSIQUES)]


def save_tags(tags: list[str]) -> None:
    save_json(TAGS_FILE, {"tags": [t[:8].ljust(8, "_") for t in tags]})
