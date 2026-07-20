#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import requests

from .common import PaperRecord, REQUEST_TIMEOUT, clean_text, normalize_doi, requests_get_json


SOURCE_NAME = "pubmed"
DISPLAY_NAME = "PubMed"


def search_records(
    query: str,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
    api_key: str = "",
    contact_email: str = "",
    **_: object,
) -> list[PaperRecord]:
    esearch_params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": min(max(limit, 1), 200),
        "sort": "pub date",
    }
    if start_date:
        esearch_params["mindate"] = start_date.isoformat()
    if end_date:
        esearch_params["maxdate"] = end_date.isoformat()
    if start_date or end_date:
        esearch_params["datetype"] = "pdat"
    if api_key:
        esearch_params["api_key"] = api_key
    if contact_email:
        esearch_params["email"] = contact_email
        esearch_params["tool"] = "AiResearchDaily"

    search_data = requests_get_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params=esearch_params,
    )
    ids = (search_data.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return []

    efetch_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml",
    }
    if api_key:
        efetch_params["api_key"] = api_key
    if contact_email:
        efetch_params["email"] = contact_email
        efetch_params["tool"] = "AiResearchDaily"
    response = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params=efetch_params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    records: list[PaperRecord] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = clean_text(article.findtext(".//PMID", default=""))
        abstract = " ".join(
            clean_text(node.text)
            for node in article.findall(".//Abstract/AbstractText")
            if clean_text(node.text)
        )
        journal = clean_text(article.findtext(".//Journal/Title", default=""))
        year = clean_text(article.findtext(".//JournalIssue/PubDate/Year", default=""))
        medline_date = clean_text(article.findtext(".//JournalIssue/PubDate/MedlineDate", default=""))
        if not year and medline_date:
            year = medline_date[:4]
        doi = ""
        for article_id in article.findall(".//ArticleIdList/ArticleId"):
            if article_id.attrib.get("IdType", "").lower() == "doi":
                doi = normalize_doi(article_id.text)
                break
        authors = []
        for author in article.findall(".//AuthorList/Author"):
            name = clean_text(" ".join([
                author.findtext("ForeName", default=""),
                author.findtext("LastName", default=""),
            ]))
            if name:
                authors.append(name)
        records.append(PaperRecord(
            query=query,
            paperId=pmid,
            source=SOURCE_NAME,
            title=clean_text(article.findtext(".//ArticleTitle", default="")),
            authors="; ".join(authors),
            abstract=abstract,
            year=year,
            venue=journal,
            publicationDate=year,
            doi=doi,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            source_ids={SOURCE_NAME: pmid} if pmid else {},
            external_ids={"PMID": pmid, "DOI": doi},
        ))
    return records


def fetch_by_doi(
    doi: str,
    api_key: str = "",
    contact_email: str = "",
) -> PaperRecord | None:
    doi = normalize_doi(doi)
    if not doi:
        return None
    matches = search_records(
        query=f"{doi}[doi]",
        limit=1,
        api_key=api_key,
        contact_email=contact_email,
    )
    for match in matches:
        if normalize_doi(match.doi) == doi:
            return match
    return matches[0] if matches else None
