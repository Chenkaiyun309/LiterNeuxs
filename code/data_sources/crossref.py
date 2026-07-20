#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from .common import (
    PaperRecord,
    clean_text,
    date_in_range,
    first_date_from_parts,
    normalize_doi,
    requests_get_json,
    year_from_date,
)


SOURCE_NAME = "crossref"
DISPLAY_NAME = "Crossref"


def search_records(
    query: str,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
    contact_email: str = "",
    **_: object,
) -> list[PaperRecord]:
    params = {
        "query.bibliographic": query,
        "rows": min(max(limit, 1), 100),
        "sort": "published",
        "order": "desc",
    }
    filters = []
    if start_date:
        filters.append(f"from-pub-date:{start_date.isoformat()}")
    if end_date:
        filters.append(f"until-pub-date:{end_date.isoformat()}")
    if filters:
        params["filter"] = ",".join(filters)
    if contact_email:
        params["mailto"] = contact_email
    data = requests_get_json("https://api.crossref.org/works", params=params)

    records: list[PaperRecord] = []
    for item in (data.get("message") or {}).get("items", []):
        publication_date = (
            first_date_from_parts(item.get("published-print"))
            or first_date_from_parts(item.get("published-online"))
            or first_date_from_parts(item.get("published"))
            or first_date_from_parts(item.get("issued"))
        )
        if not date_in_range(publication_date, start_date, end_date):
            continue
        authors = []
        for author in item.get("author") or []:
            name = clean_text(" ".join(x for x in [author.get("given"), author.get("family")] if x))
            if name:
                authors.append(name)
        doi = normalize_doi(item.get("DOI"))
        records.append(PaperRecord(
            query=query,
            paperId=doi,
            source=SOURCE_NAME,
            title=clean_text((item.get("title") or [""])[0]),
            authors="; ".join(authors),
            abstract=clean_text(item.get("abstract")),
            year=year_from_date(publication_date),
            venue=clean_text((item.get("container-title") or [""])[0]),
            volume=clean_text(item.get("volume")),
            issue=clean_text(item.get("issue")),
            publicationDate=publication_date,
            citationCount=clean_text(item.get("is-referenced-by-count")),
            doi=doi,
            url=clean_text(item.get("URL")),
            source_ids={SOURCE_NAME: doi} if doi else {},
            external_ids={"DOI": doi} if doi else {},
        ))
    return records


def fetch_by_doi(doi: str, contact_email: str = "") -> PaperRecord | None:
    if not doi:
        return None
    try:
        params = {"mailto": contact_email} if contact_email else None
        data = requests_get_json(f"https://api.crossref.org/works/{quote(doi, safe='')}", params=params)
    except Exception:
        return None
    item = data.get("message") or {}
    if not item:
        return None
    publication_date = (
        first_date_from_parts(item.get("published-print"))
        or first_date_from_parts(item.get("published-online"))
        or first_date_from_parts(item.get("published"))
        or first_date_from_parts(item.get("issued"))
    )
    authors = []
    for author in item.get("author") or []:
        name = clean_text(" ".join(x for x in [author.get("given"), author.get("family")] if x))
        if name:
            authors.append(name)
    return PaperRecord(
        source=SOURCE_NAME,
        title=clean_text((item.get("title") or [""])[0]),
        authors="; ".join(authors),
        abstract=clean_text(item.get("abstract")),
        year=year_from_date(publication_date),
        venue=clean_text((item.get("container-title") or [""])[0]),
        volume=clean_text(item.get("volume")),
        issue=clean_text(item.get("issue")),
        publicationDate=publication_date,
        citationCount=clean_text(item.get("is-referenced-by-count")),
        doi=normalize_doi(item.get("DOI")),
        url=clean_text(item.get("URL")),
        source_ids={SOURCE_NAME: doi},
        external_ids={"DOI": doi},
    )
