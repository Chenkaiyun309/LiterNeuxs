#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from .common import PaperRecord, clean_text, normalize_doi, requests_get_json, year_from_date


SOURCE_NAME = "openalex"
DISPLAY_NAME = "OpenAlex"


def reconstruct_abstract(index: object) -> str:
    if not isinstance(index, dict):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in index.items():
        if not isinstance(indexes, list):
            continue
        for item in indexes:
            if isinstance(item, int):
                positions[item] = str(word)
    return " ".join(positions[i] for i in sorted(positions))


def search_records(
    query: str,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
    contact_email: str = "",
    **_: object,
) -> list[PaperRecord]:
    filters = []
    if start_date:
        filters.append(f"from_publication_date:{start_date.isoformat()}")
    if end_date:
        filters.append(f"to_publication_date:{end_date.isoformat()}")
    params = {
        "search": query,
        "per-page": min(max(limit, 1), 200),
        "sort": "publication_date:desc",
    }
    if filters:
        params["filter"] = ",".join(filters)
    if contact_email:
        params["mailto"] = contact_email
    data = requests_get_json("https://api.openalex.org/works", params=params)

    records: list[PaperRecord] = []
    for item in data.get("results", []):
        source = item.get("primary_location", {}).get("source") or {}
        authorships = item.get("authorships") or []
        author_names = [
            clean_text((authorship.get("author") or {}).get("display_name"))
            for authorship in authorships
            if clean_text((authorship.get("author") or {}).get("display_name"))
        ]
        institution_names = sorted({
            name
            for authorship in authorships
            for institution in (authorship.get("institutions") or [])
            if (name := clean_text(institution.get("display_name")))
        })
        openalex_id = clean_text(item.get("id"))
        publication_date = clean_text(item.get("publication_date"))
        records.append(PaperRecord(
            query=query,
            paperId=openalex_id,
            source=SOURCE_NAME,
            title=clean_text(item.get("display_name")),
            authors="; ".join(author_names),
            institutions="; ".join(institution_names),
            abstract=clean_text(reconstruct_abstract(item.get("abstract_inverted_index"))),
            year=clean_text(item.get("publication_year")) or year_from_date(publication_date),
            venue=clean_text(source.get("display_name")),
            publicationDate=publication_date,
            citationCount=clean_text(item.get("cited_by_count")),
            doi=normalize_doi(item.get("doi")),
            url=clean_text(item.get("doi") or item.get("id")),
            pdf_url=clean_text((item.get("best_oa_location") or {}).get("pdf_url")),
            source_ids={SOURCE_NAME: openalex_id} if openalex_id else {},
            external_ids=item.get("ids") or {},
        ))
    return records


def fetch_by_doi(doi: str, contact_email: str = "") -> PaperRecord | None:
    if not doi:
        return None
    try:
        params = {"mailto": contact_email} if contact_email else None
        data = requests_get_json(f"https://api.openalex.org/works/doi:{quote(doi, safe='')}", params=params)
    except Exception:
        return None
    source = data.get("primary_location", {}).get("source") or {}
    authorships = data.get("authorships") or []
    author_names = [
        clean_text((authorship.get("author") or {}).get("display_name"))
        for authorship in authorships
        if clean_text((authorship.get("author") or {}).get("display_name"))
    ]
    institution_names = sorted({
        name
        for authorship in authorships
        for institution in (authorship.get("institutions") or [])
        if (name := clean_text(institution.get("display_name")))
    })
    openalex_id = clean_text(data.get("id"))
    publication_date = clean_text(data.get("publication_date"))
    return PaperRecord(
        source=SOURCE_NAME,
        title=clean_text(data.get("display_name")),
        authors="; ".join(author_names),
        institutions="; ".join(institution_names),
        abstract=clean_text(reconstruct_abstract(data.get("abstract_inverted_index"))),
        year=clean_text(data.get("publication_year")) or year_from_date(publication_date),
        venue=clean_text(source.get("display_name")),
        publicationDate=publication_date,
        citationCount=clean_text(data.get("cited_by_count")),
        doi=normalize_doi(data.get("doi")),
        url=clean_text(data.get("doi") or data.get("id")),
        pdf_url=clean_text((data.get("best_oa_location") or {}).get("pdf_url")),
        source_ids={SOURCE_NAME: openalex_id} if openalex_id else {},
        external_ids=data.get("ids") or {},
    )
