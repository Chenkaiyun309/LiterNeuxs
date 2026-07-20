#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "llm_provider": "openai_compatible",
    "llm_base_url": "",
    "llm_api_key": "",
    "model": "",
    "max_papers_for_llm": 15,
    "report_style": "科研日报",
    "report_data_source": "csv",
    "report_collection_id": "",
    "report_input_mode": "abstract_only",
    "temperature": 0,
    "top_p": 0.9,
    "num_predict": 6000,
    "max_retry": 3,
    "topic_override": "",
    "min_research_content_chars": 350,
    "keep_empty_abstract": False,
    "save_debug_files": False,
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


def _to_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _to_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def normalize_settings(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = dict(DEFAULT_SETTINGS)
    if current:
        previous.update(current)

    provider = str(payload.get("llm_provider") or "openai_compatible").strip().lower()
    if provider not in {"openai_compatible", "ollama"}:
        provider = "openai_compatible"

    report_input_mode = str(payload.get("report_input_mode") or "abstract_only").strip()
    if report_input_mode not in {"abstract_only", "fulltext_only", "abstract_plus_fulltext"}:
        report_input_mode = "abstract_only"

    report_data_source = str(payload.get("report_data_source") or "csv").strip().lower()
    if report_data_source not in {"csv", "collection", "library"}:
        report_data_source = "csv"

    api_key = str(payload.get("llm_api_key") or "").strip()
    if not api_key and payload.get("preserve_api_key", True):
        api_key = str(previous.get("llm_api_key") or "")

    return {
        "llm_provider": provider,
        "llm_base_url": str(payload.get("llm_base_url") or payload.get("ollama_base_url") or "").strip().rstrip("/"),
        "llm_api_key": api_key,
        "model": str(payload.get("model") or "").strip(),
        "max_papers_for_llm": _to_int(payload.get("max_papers_for_llm"), 15, 1, 200),
        "report_style": str(payload.get("report_style") or "科研日报").strip() or "科研日报",
        "report_data_source": report_data_source,
        "report_collection_id": str(payload.get("report_collection_id") or "").strip(),
        "report_input_mode": report_input_mode,
        "temperature": _to_float(payload.get("temperature"), 0, 0, 2),
        "top_p": _to_float(payload.get("top_p"), 0.9, 0, 1),
        "num_predict": _to_int(payload.get("num_predict"), 6000, 100, 200000),
        "max_retry": _to_int(payload.get("max_retry"), 3, 0, 10),
        "topic_override": str(payload.get("topic_override") or "").strip(),
        "min_research_content_chars": _to_int(payload.get("min_research_content_chars"), 350, 0, 20000),
        "keep_empty_abstract": bool(payload.get("keep_empty_abstract")),
        "save_debug_files": bool(payload.get("save_debug_files")),
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
