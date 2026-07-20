#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from .node_classifier import normalize_term

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"MATERIAL", "PROCESS", "STRUCTURE", "PROPERTY"}
ALLOWED_RELATIONS = {
    "affects", "enhances", "induces", "refines", "promotes", "controls",
    "increases", "reduces", "inhibits", "forms", "exhibits", "limits",
    "modifies", "associated_with", "processed_by",
}


def config_int(config: dict[str, Any], key: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def llm_enabled(config: dict[str, Any] | None) -> bool:
    config = config or {}
    provider = str(config.get("llm_provider") or "").strip()
    if provider == "openai_compatible":
        return bool(str(config.get("llm_api_key") or "").strip() and str(config.get("llm_base_url") or "").strip())
    if provider == "ollama":
        return bool(str(config.get("ollama_base_url") or "").strip())
    return False


def extract_triplets_with_llm(
    text: str,
    candidate_terms: list[tuple[str, str]],
    config: dict[str, Any] | None,
    paper_index: int,
) -> list[dict]:
    if not llm_enabled(config):
        return []

    config = config or {}
    provider = str(config.get("llm_provider") or "openai_compatible").strip()
    model = str(config.get("model") or "").strip()
    candidate_lookup = {str(term).strip().lower(): (str(term).strip(), node_type) for term, node_type in candidate_terms if str(term).strip()}
    prompt = build_prompt(text, candidate_terms)
    try:
        if provider == "ollama":
            content = call_ollama(prompt, config, model)
        else:
            content = call_openai_compatible(prompt, config, model)
        return validate_triplets(parse_json_object(content), paper_index, candidate_lookup)
    except Exception as exc:
        logger.warning("LLM 三元组抽取失败 (paper_index=%s): %s", paper_index, exc)
        return []


def build_prompt(text: str, candidate_terms: list[tuple[str, str]]) -> str:
    candidates = [{"term": term, "type": node_type} for term, node_type in candidate_terms]
    material_terms = [term for term, node_type in candidate_terms if node_type == "MATERIAL"]
    return (
        "You are extracting a materials-science Material-Process-Structure-Property knowledge graph.\n"
        "Return ONLY valid JSON with key triplets. Each triplet must use node types "
        "MATERIAL, PROCESS, STRUCTURE, PROPERTY. Prefer specific microstructure nodes "
        "such as lamellar microstructure, grain boundary, Cr-rich precipitates, oxide scale.\n"
        "Prefer complete MATERIAL -> PROCESS -> STRUCTURE -> PROPERTY chains when supported. "
        "Every PROCESS, STRUCTURE, or PROPERTY relation should be anchored to the material system "
        "when the material is present in the text. Include material-context triplets such as "
        "(Ti-Nb, processed_by, sintering), (Nb alloy, exhibits, lamellar microstructure), "
        "and (Nb alloy, associated_with, strength) when supported.\n"
        "Avoid generic nodes like phase or microstructure if a more specific phrase is available.\n"
        "Allowed relations: affects, enhances, induces, refines, promotes, controls, "
        "increases, reduces, inhibits, forms, exhibits, limits, modifies, associated_with, processed_by.\n"
        "Use processed_by only for MATERIAL -> PROCESS context links.\n"
        "Keep only evidence-supported causal or mechanistic relations.\n\n"
        f"Candidate terms: {json.dumps(candidates, ensure_ascii=False)}\n\n"
        f"Material anchors: {json.dumps(material_terms, ensure_ascii=False)}\n\n"
        f"Text:\n{text[:5000]}\n\n"
        "JSON schema: {\"triplets\":[{\"subject\":\"...\",\"subject_type\":\"PROCESS\","
        "\"relation\":\"induces\",\"object\":\"...\",\"object_type\":\"STRUCTURE\","
        "\"evidence\":\"short evidence text\",\"confidence\":0.0}]}"
    )


def call_openai_compatible(prompt: str, config: dict[str, Any], model: str) -> str:
    base_url = str(config.get("llm_base_url") or "").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.get('llm_api_key')}",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "top_p": 0.9,
    }
    connect_timeout = config_int(config, "llm_connect_timeout_sec", 10, 5, 30)
    read_timeout = config_int(config, "llm_timeout_sec", 45, 10, 180)
    response = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def call_ollama(prompt: str, config: dict[str, Any], model: str) -> str:
    base_url = str(config.get("ollama_base_url") or "").rstrip("/")
    connect_timeout = config_int(config, "llm_connect_timeout_sec", 10, 5, 30)
    read_timeout = config_int(config, "llm_timeout_sec", 75, 10, 240)
    response = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0, "top_p": 0.9},
        },
        timeout=(connect_timeout, read_timeout),
    )
    response.raise_for_status()
    data = response.json()
    return data.get("message", {}).get("content", "")


def parse_json_object(content: str) -> dict:
    text = str(content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0)
    return json.loads(text)


def canonicalize_term(term: str, node_type: str, candidate_lookup: dict[str, tuple[str, str]]) -> tuple[str, str]:
    normalized = normalize_term(term)
    if not normalized:
        return "", node_type
    match = candidate_lookup.get(normalized.lower())
    if match:
        return match
    return normalized, node_type


def validate_triplets(
    data: dict,
    paper_index: int,
    candidate_lookup: dict[str, tuple[str, str]] | None = None,
) -> list[dict]:
    candidate_lookup = candidate_lookup or {}
    valid: list[dict] = []
    for item in data.get("triplets", []):
        subject = str(item.get("subject") or "").strip()
        obj = str(item.get("object") or "").strip()
        subject_type = str(item.get("subject_type") or "").strip().upper()
        object_type = str(item.get("object_type") or "").strip().upper()
        subject, subject_type = canonicalize_term(subject, subject_type, candidate_lookup)
        obj, object_type = canonicalize_term(obj, object_type, candidate_lookup)
        relation = str(item.get("relation") or "affects").strip()
        if not subject or not obj or subject == obj:
            continue
        if subject_type not in ALLOWED_TYPES or object_type not in ALLOWED_TYPES:
            continue
        if relation not in ALLOWED_RELATIONS:
            relation = "affects"
        try:
            confidence = float(item.get("confidence", 0.75))
        except (TypeError, ValueError):
            confidence = 0.75
        valid.append({
            "subject": subject,
            "subject_type": subject_type,
            "relation": relation,
            "object": obj,
            "object_type": object_type,
            "evidence": str(item.get("evidence") or "")[:500],
            "confidence": max(0.0, min(1.0, confidence)),
            "paper_index": int(paper_index),
            "source": "llm",
        })
    return valid
