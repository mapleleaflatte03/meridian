#!/usr/bin/env python3
"""Shared Meridian product configuration helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_LLM_BASE_URL = "http://127.0.0.1:11434/v1/chat/completions"
DEFAULT_LLM_MODEL = "qwen2.5:7b"
DEFAULT_ALLOWED_ORIGIN = "https://app.welliam.codes"
CONFIG_PATH = Path(__file__).resolve().parent / "meridian_config.json"

DEFAULT_CONFIG = {
    "llm_base_url": DEFAULT_LLM_BASE_URL,
    "llm_model": DEFAULT_LLM_MODEL,
    "llm_api_key": "",
    "telegram_bot_token": "",
    "allowed_origin": DEFAULT_ALLOWED_ORIGIN,
}


def load_config(*, required: bool = False) -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        if required:
            raise FileNotFoundError(CONFIG_PATH)
        return dict(DEFAULT_CONFIG)
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"config at {CONFIG_PATH} must be a JSON object")
    merged = dict(DEFAULT_CONFIG)
    for key, value in data.items():
        if value is not None:
            merged[str(key)] = value
    return merged


def save_config(config: dict[str, Any]) -> Path:
    merged = dict(DEFAULT_CONFIG)
    for key, value in config.items():
        if value is not None:
            merged[str(key)] = value
    CONFIG_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return CONFIG_PATH
