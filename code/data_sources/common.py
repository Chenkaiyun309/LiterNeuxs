#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests


REQUEST_TIMEOUT = (15, 45)

OUTPUT_COLUMNS = [
    "query",
    "paperId",
    "source",
    "title",
    "authors",
    "institutions",
    "abstract",
    "year",
    "venue",
    "volume",
    "issue",
    "publicationDate",
    "citationCount",
    "doi",
    "url",
    "pdf_url",
    "source_ids_json",
    "externalIds_json",
    "enrichment_sources",
]


@dataclass
class PaperRecord:
    query: str = ""
    paperId: str = ""
    source: str = ""
    title: str = ""
    authors: str = ""
    institutions: str = ""
    abstract: str = ""
    year: str = ""
    venue: str = ""
    volume: str = ""
    issue: str = ""
    publicationDate: str = ""
    citationCount: str = ""
    doi: str = ""
    url: str = ""
    pdf_url: str = ""
    source_ids: dict[str, str] = field(default_factory=dict)
    external_ids: dict[str, Any] = field(default_factory=dict)
    enrichment_sources: set[str] = field(default_factory=set)

    def to_row(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "paperId": self.paperId,
            "source": self.source,
            "title": self.title,
            "authors": self.authors,
            "institutions": self.institutions,
            "abstract": self.abstract,
            "year": self.year,
            "venue": self.venue,
            "volume": self.volume,
            "issue": self.issue,
            "publicationDate": self.publicationDate,
            "citationCount": self.citationCount,
            "doi": self.doi,
            "url": self.url,
            "pdf_url": self.pdf_url,
            "source_ids_json": json.dumps(self.source_ids, ensure_ascii=False),
            "externalIds_json": json.dumps(self.external_ids, ensure_ascii=False),
            "enrichment_sources": ";".join(sorted(self.enrichment_sources)),
        }


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_doi(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    text = re.sub(r"^doi:\s*", "", text, flags=re.I)
    return text.strip().lower()


def normalize_title_key(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_query_name(query: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", query.strip(), flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "query"


def parse_date_input(value: str | None) -> date | None:
    raw = clean_text(value)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"日期格式错误：{raw}，请使用 YYYY-MM-DD。") from exc


def date_in_range(value: str, start_date: date | None, end_date: date | None) -> bool:
    text = clean_text(value)
    if not text:
        return True
    try:
        item_date = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        try:
            year = int(text[:4])
        except ValueError:
            return True
        item_start = date(year, 1, 1)
        item_end = date(year, 12, 31)
        if start_date and item_end < start_date:
            return False
        if end_date and item_start > end_date:
            return False
        return True
    if start_date and item_date < start_date:
        return False
    if end_date and item_date > end_date:
        return False
    return True


def year_from_date(value: str) -> str:
    text = clean_text(value)
    return text[:4] if re.match(r"^\d{4}", text) else ""


def requests_get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict:
    response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def first_date_from_parts(parts: Any) -> str:
    try:
        date_parts = parts["date-parts"][0]
    except (TypeError, KeyError, IndexError):
        return ""
    if not date_parts:
        return ""
    year = str(date_parts[0]).zfill(4)
    month = str(date_parts[1]).zfill(2) if len(date_parts) > 1 else "01"
    day = str(date_parts[2]).zfill(2) if len(date_parts) > 2 else "01"
    return f"{year}-{month}-{day}"
