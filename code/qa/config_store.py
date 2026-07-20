#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "provider": "openai_compatible",
    "base_url": "",
    "api_key": "",
    "model": "",
    "embedding_base_url": "",
    "embedding_api_key": "",
    "embedding_model": "",
    "retrieval_mode": "lexical",
    "top_k": 10,
    "reranker_enabled": False,
    "reranker_model": "BAAI/bge-reranker-v2-m3",
    "reranker_candidate_k": 40,
    "reranker_batch_size": 4,
    "reranker_max_length": 512,
    "reranker_device": "auto",
    "answer_depth": "detailed",
    "temperature": 0.1,
    "max_tokens": 3200,
    "request_timeout_sec": 180,
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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
        for key in settings:
            if key in payload:
                settings[key] = payload[key]
    return normalize_settings(settings)


def normalize_settings(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = dict(DEFAULT_SETTINGS)
    if current:
        previous.update(current)
    provider = str(payload.get("provider") or "openai_compatible").strip()
    if provider not in {"openai_compatible", "ollama"}:
        provider = "openai_compatible"
    retrieval_mode = str(payload.get("retrieval_mode") or "lexical").strip()
    if retrieval_mode not in {"lexical", "hybrid"}:
        retrieval_mode = "lexical"
    reranker_device = str(payload.get("reranker_device") or "auto").strip().lower()
    if reranker_device not in {"auto", "mps", "cpu"}:
        reranker_device = "auto"
    answer_depth = str(payload.get("answer_depth") or "detailed").strip().lower()
    if answer_depth not in {"concise", "standard", "detailed"}:
        answer_depth = "detailed"

    api_key = str(payload.get("api_key") or "").strip()
    embedding_api_key = str(payload.get("embedding_api_key") or "").strip()
    if not api_key and payload.get("preserve_api_key", True):
        api_key = str(previous.get("api_key") or "")
    if not embedding_api_key and payload.get("preserve_embedding_api_key", True):
        embedding_api_key = str(previous.get("embedding_api_key") or "")

    return {
        "provider": provider,
        "base_url": str(payload.get("base_url") or "").strip().rstrip("/"),
        "api_key": api_key,
        "model": str(payload.get("model") or "").strip(),
        "embedding_base_url": str(payload.get("embedding_base_url") or "").strip().rstrip("/"),
        "embedding_api_key": embedding_api_key,
        "embedding_model": str(payload.get("embedding_model") or "").strip(),
        "retrieval_mode": retrieval_mode,
        "top_k": min(20, max(4, int(payload.get("top_k") or 10))),
        "reranker_enabled": _as_bool(payload.get("reranker_enabled", False)),
        "reranker_model": str(payload.get("reranker_model") or "BAAI/bge-reranker-v2-m3").strip(),
        "reranker_candidate_k": min(100, max(10, int(payload.get("reranker_candidate_k") or 40))),
        "reranker_batch_size": min(16, max(1, int(payload.get("reranker_batch_size") or 4))),
        "reranker_max_length": min(1024, max(128, int(payload.get("reranker_max_length") or 512))),
        "reranker_device": reranker_device,
        "answer_depth": answer_depth,
        "temperature": min(1.0, max(0.0, float(payload.get("temperature", 0.1)))),
        "max_tokens": min(8000, max(512, int(payload.get("max_tokens") or 3200))),
        "request_timeout_sec": min(900, max(30, int(payload.get("request_timeout_sec") or 180))),
    }


def save_settings(path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    config_path = Path(path)
    current = load_settings(config_path)
    settings = normalize_settings(payload, current=current)
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
        if key not in {"api_key", "embedding_api_key"}
    } | {
        "has_api_key": bool(str(settings.get("api_key") or "").strip()),
        "has_embedding_api_key": bool(str(settings.get("embedding_api_key") or "").strip()),
    }


def validate_generation_settings(settings: dict[str, Any]) -> str:
    if not str(settings.get("base_url") or "").strip():
        return "请先配置大模型服务地址"
    if not str(settings.get("model") or "").strip():
        return "请先配置大模型名称"
    if settings.get("provider") == "openai_compatible" and not str(settings.get("api_key") or "").strip():
        return "请先配置大模型访问密钥"
    return ""


def embedding_is_configured(settings: dict[str, Any]) -> bool:
    if str(settings.get("retrieval_mode") or "") != "hybrid":
        return False
    base_url = str(settings.get("embedding_base_url") or settings.get("base_url") or "").strip()
    model = str(settings.get("embedding_model") or "").strip()
    api_key = str(settings.get("embedding_api_key") or settings.get("api_key") or "").strip()
    return bool(base_url and model and api_key)
