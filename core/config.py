# -*- coding: utf-8 -*-
"""配置读写与默认值。"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
TASKS_DIR = ROOT / "tasks"
WEB_DIR = ROOT / "web"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
TEMPLATES_PATH = CONFIG_DIR / "templates.json"
DICTIONARIES_PATH = CONFIG_DIR / "dictionaries.json"
STOPWORDS_PATH = CONFIG_DIR / "stopwords.txt"
BANNED_WORDS_PATH = CONFIG_DIR / "banned_words.txt"
BRANDS_PATH = CONFIG_DIR / "brands.txt"

_LOCK = threading.RLock()

DEFAULT_SETTINGS = {
    "server": {"host": "127.0.0.1", "port": 8765, "open_browser": True},
    "download": {
        "timeout": 30,
        "retries": 3,
        "concurrency": 4,
        "delay": 0.1,
        "max_file_mb": 40,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "cookie": "",
        "referer": "https://detail.1688.com/",
    },
    "specs": {
        "main_pc": {"width": 800, "height": 800, "max_bytes": 3145728, "target_bytes": 512000},
        "main_mobile": {"width": 750, "height": 1000, "max_bytes": 3145728, "target_bytes": 512000},
        "white": {"width": 800, "height": 800, "max_bytes": 3145728, "target_bytes": 512000},
        "white_mobile": {"width": 750, "height": 1000, "max_bytes": 3145728, "target_bytes": 512000},
        "detail": {
            "width": 750,
            "max_height": 2000,
            "segment_height": 1500,
            "max_bytes": 3145728,
            "target_bytes": 900000,
        },
        "sku": {"width": 800, "height": 800, "max_bytes": 3145728, "target_bytes": 512000},
    },
    "fonts": {
        "bold": "C:/Windows/Fonts/msyhbd.ttc",
        "regular": "C:/Windows/Fonts/msyh.ttc",
    },
    "export": {"zip_ascii_names": True},
    "ai": {
        "enabled": False,
        "provider": "ollama",
        "ollama_url": "http://127.0.0.1:11434",
        "base_url": "",
        "api_key": "",
        "text_model": "",
        "vision_model": "",
        "timeout": 20,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def ensure_dirs() -> None:
    for path in (CONFIG_DIR, TASKS_DIR, WEB_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return copy.deepcopy(default)


def load_settings() -> dict:
    raw = _read_json(SETTINGS_PATH, {})
    return _deep_merge(DEFAULT_SETTINGS, raw if isinstance(raw, dict) else {})


def save_settings(data: dict) -> dict:
    settings = _deep_merge(load_settings(), data if isinstance(data, dict) else {})
    with _LOCK:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    return settings


def get_specs() -> dict:
    return load_settings().get("specs", {})


def get_spec(kind: str) -> dict:
    specs = get_specs()
    return specs.get(kind, DEFAULT_SETTINGS["specs"].get(kind, {}))


def load_templates() -> dict:
    data = _read_json(TEMPLATES_PATH, {})
    if not isinstance(data, dict):
        return {}
    return data


def load_dictionaries() -> dict:
    data = _read_json(DICTIONARIES_PATH, {})
    if not isinstance(data, dict):
        return {}
    return data


def read_lines(path: Path) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    except OSError:
        return []


def load_stopwords() -> set[str]:
    return set(read_lines(STOPWORDS_PATH))


def load_banned_words() -> set[str]:
    return set(read_lines(BANNED_WORDS_PATH))


def load_brands() -> set[str]:
    return set(read_lines(BRANDS_PATH))
