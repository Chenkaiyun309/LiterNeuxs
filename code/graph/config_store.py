#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "hybrid",
    "input_source": "abstract",
    "max_chunks_per_paper": 20,
    "llm_provider": "openai_compatible",
    "llm_base_url": "",
    "llm_api_key": "",
    "model": "",
}


def load_settings(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    settings = dict(DEFAULT_SETTINGS)
    if not config_path.exists():
        return settings
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if isinstance(payload, dict):
        settings.update({key: payload[key] for key in settings if key in payload})
    return normalize_settings(settings)


def normalize_settings(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = dict(DEFAULT_SETTINGS)
    if current:
        previous.update(current)

    mode = str(payload.get("mode") or "hybrid").strip().lower()
    if mode not in {"rule", "hybrid", "llm"}:
        mode = "hybrid"

    input_source = str(payload.get("input_source") or "abstract").strip().lower()
    if input_source not in {"abstract", "chunks", "abstract_chunks"}:
        input_source = "abstract"

    provider = str(payload.get("llm_provider") or "openai_compatible").strip().lower()
    if provider not in {"openai_compatible", "ollama"}:
        provider = "openai_compatible"

    api_key = str(payload.get("llm_api_key") or "").strip()
    if not api_key and payload.get("preserve_api_key", True):
        api_key = str(previous.get("llm_api_key") or "")

    return {
        "mode": mode,
        "input_source": input_source,
        "max_chunks_per_paper": min(20, max(1, int(payload.get("max_chunks_per_paper") or 20))),
        "llm_provider": provider,
        "llm_base_url": str(payload.get("llm_base_url") or "").strip().rstrip("/"),
        "llm_api_key": api_key,
        "model": str(payload.get("model") or "").strip(),
    }


def save_settings(path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    config_path = Path(path)
    settings = normalize_settings(payload, current=load_settings(config_path))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = config_path.with_suffix(f"{config_path.suffix}.tmp")
    temp_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(config_path)
    os.chmod(config_path, 0o600)
    return settings


def public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in settings.items()
        if key != "llm_api_key"
    } | {
        "has_api_key": bool(str(settings.get("llm_api_key") or "").strip()),
    }
