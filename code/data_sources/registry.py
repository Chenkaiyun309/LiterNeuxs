#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from types import ModuleType
from typing import Iterable

from . import arxiv, crossref, openalex, pubmed, semantic_scholar, springer_nature


DEFAULT_SOURCES = ["semantic_scholar", "openalex", "crossref"]

SOURCES: dict[str, ModuleType] = {
    "semantic_scholar": semantic_scholar,
    "openalex": openalex,
    "crossref": crossref,
    "arxiv": arxiv,
    "pubmed": pubmed,
    "springer_nature": springer_nature,
}

ALL_SOURCES = list(SOURCES.keys())


def get_source(name: str) -> ModuleType:
    try:
        return SOURCES[name]
    except KeyError as exc:
        available = ", ".join(ALL_SOURCES)
        raise ValueError(f"未知文献数据库: {name}。可用数据库: {available}") from exc


def selected_sources_or_default(sources: Iterable[str] | None) -> list[str]:
    cleaned = [source for source in (sources or []) if source in SOURCES]
    return cleaned or DEFAULT_SOURCES.copy()
