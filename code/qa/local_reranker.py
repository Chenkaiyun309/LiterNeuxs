#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_MODEL_ID = "BAAI/bge-reranker-v2-m3"
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,160}$")

_RUNTIME_LOCK = threading.RLock()
_RUNTIME: dict[str, Any] = {}


class LocalRerankerError(RuntimeError):
    """Raised when the local reranker cannot be deployed or used."""


def model_directory(models_root: str | Path, model_id: str = DEFAULT_MODEL_ID) -> Path:
    normalized = str(model_id or DEFAULT_MODEL_ID).strip()
    if not MODEL_ID_RE.fullmatch(normalized) or ".." in normalized:
        raise LocalRerankerError("本地 Reranker 模型名称无效")
    return Path(models_root) / normalized.replace("/", "--")


def model_is_deployed(model_path: str | Path) -> bool:
    path = Path(model_path)
    if not (path / "config.json").is_file():
        return False
    return any(path.glob("*.safetensors")) or any(path.glob("*.bin"))


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _select_device(requested: str = "auto") -> str:
    try:
        import torch
    except ImportError as exc:
        raise LocalRerankerError("缺少 PyTorch，无法运行本地 Reranker") from exc
    normalized = str(requested or "auto").strip().lower()
    if normalized == "auto":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    if normalized == "mps" and not torch.backends.mps.is_available():
        return "cpu"
    if normalized not in {"mps", "cpu"}:
        raise LocalRerankerError("Reranker 设备仅支持 auto、mps 或 cpu")
    return normalized


def deploy_model(models_root: str | Path, model_id: str = DEFAULT_MODEL_ID) -> dict[str, Any]:
    target = model_directory(models_root, model_id)
    target.mkdir(parents=True, exist_ok=True)
    if model_is_deployed(target):
        return status(models_root, model_id=model_id)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise LocalRerankerError("缺少 huggingface_hub，无法下载本地模型") from exc
    snapshot_download(
        repo_id=model_id,
        local_dir=str(target),
        allow_patterns=[
            "*.json", "*.model", "*.txt", "*.safetensors", "*.safetensors.index.json",
            "tokenizer*", "sentencepiece*", "special_tokens_map.json",
        ],
    )
    if not model_is_deployed(target):
        raise LocalRerankerError("模型文件下载不完整，未找到可用权重")
    return status(models_root, model_id=model_id)


def _load_runtime(model_path: Path, requested_device: str) -> dict[str, Any]:
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise LocalRerankerError("缺少 torch 或 transformers，无法运行本地 Reranker") from exc
    if not model_is_deployed(model_path):
        raise LocalRerankerError("本地 Reranker 尚未部署")
    device = _select_device(requested_device)
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(str(model_path), local_files_only=True)
    model.eval()
    if device == "mps":
        model = model.to(device=device, dtype=torch.float16)
    else:
        model = model.to(device)
    return {
        "path": str(model_path.resolve()),
        "device": device,
        "model": model,
        "tokenizer": tokenizer,
    }


def _runtime(model_path: Path, requested_device: str) -> dict[str, Any]:
    key = f"{model_path.resolve()}::{requested_device}"
    with _RUNTIME_LOCK:
        if _RUNTIME.get("key") != key:
            _RUNTIME.clear()
            _RUNTIME.update({"key": key, **_load_runtime(model_path, requested_device)})
        return _RUNTIME


def _passage(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("title") or "").strip(),
        str(item.get("section_title") or "").strip(),
        str(item.get("chunk_text") or "").strip(),
    ]
    return "\n".join(part for part in parts if part)


def rerank(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    models_root: str | Path,
    model_id: str = DEFAULT_MODEL_ID,
    device: str = "auto",
    batch_size: int = 4,
    max_length: int = 512,
    top_k: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not candidates:
        return [], {"applied": False, "candidate_count": 0, "duration_ms": 0}
    model_path = model_directory(models_root, model_id)
    runtime = _runtime(model_path, device)
    model = runtime["model"]
    tokenizer = runtime["tokenizer"]
    actual_device = runtime["device"]
    safe_batch_size = min(16, max(1, int(batch_size or 4)))
    safe_max_length = min(1024, max(128, int(max_length or 512)))
    started = time.perf_counter()
    scores: list[float] = []
    try:
        import torch
        for start in range(0, len(candidates), safe_batch_size):
            batch = candidates[start:start + safe_batch_size]
            queries = [str(question or "").strip()] * len(batch)
            passages = [_passage(item) for item in batch]
            inputs = tokenizer(
                queries,
                passages,
                padding=True,
                truncation="only_second",
                max_length=safe_max_length,
                return_tensors="pt",
            )
            inputs = {key: value.to(actual_device) for key, value in inputs.items()}
            with torch.inference_mode():
                logits = model(**inputs, return_dict=True).logits.reshape(-1).float().cpu()
            scores.extend(torch.sigmoid(logits).tolist())
    except Exception as exc:
        raise LocalRerankerError(f"本地 Reranker 推理失败（{actual_device}）：{exc}") from exc

    ranked = []
    for item, score in zip(candidates, scores):
        enriched = dict(item)
        enriched["rerank_score"] = round(float(score), 6)
        ranked.append(enriched)
    ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    for index, item in enumerate(ranked, 1):
        item["rerank_rank"] = index
    duration_ms = int(round((time.perf_counter() - started) * 1000))
    return ranked[: max(1, int(top_k or 10))], {
        "applied": True,
        "model": model_id,
        "device": actual_device,
        "candidate_count": len(candidates),
        "result_count": min(len(ranked), max(1, int(top_k or 10))),
        "duration_ms": duration_ms,
    }


def status(
    models_root: str | Path,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    requested_device: str = "auto",
) -> dict[str, Any]:
    path = model_directory(models_root, model_id)
    deployed = model_is_deployed(path)
    runtime_path = str(_RUNTIME.get("path") or "")
    loaded = deployed and runtime_path == str(path.resolve())
    return {
        "model_id": model_id,
        "model_path": str(path),
        "deployed": deployed,
        "loaded": loaded,
        "device": str(_RUNTIME.get("device") or _select_device(requested_device)),
        "size_bytes": _directory_size(path),
    }
