#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import requests

from .common import PaperRecord, REQUEST_TIMEOUT, clean_text, date_in_range, normalize_doi, year_from_date


SOURCE_NAME = "arxiv"
DISPLAY_NAME = "arXiv"


def search_records(
    query: str,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
    **_: object,
) -> list[PaperRecord]:
    params = {
        "search_query": f'all:"{query}"',
        "start": 0,
        "max_results": min(max(limit * 2, limit), 100),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    response = requests.get("https://export.arxiv.org/api/query", params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    records: list[PaperRecord] = []
    for entry in root.findall("atom:entry", ns):
        published = clean_text(entry.findtext("atom:published", default="", namespaces=ns))[:10]
        if not date_in_range(published, start_date, end_date):
            continue
        authors = [
            clean_text(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = clean_text(link.attrib.get("href"))
                break
        arxiv_id = clean_text(entry.findtext("atom:id", default="", namespaces=ns))
        records.append(PaperRecord(
            query=query,
            paperId=arxiv_id,
            source=SOURCE_NAME,
            title=clean_text(entry.findtext("atom:title", default="", namespaces=ns)),
            authors="; ".join(x for x in authors if x),
            abstract=clean_text(entry.findtext("atom:summary", default="", namespaces=ns)),
            year=year_from_date(published),
            venue=clean_text(entry.findtext("arxiv:journal_ref", default="", namespaces=ns)) or "arXiv",
            publicationDate=published,
            doi=normalize_doi(entry.findtext("arxiv:doi", default="", namespaces=ns)),
            url=arxiv_id,
            pdf_url=pdf_url,
            source_ids={SOURCE_NAME: arxiv_id} if arxiv_id else {},
        ))
        if len(records) >= limit:
            break
    return records
