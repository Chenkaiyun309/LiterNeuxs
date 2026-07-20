#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import time
from datetime import date
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, HTTPError, SSLError, Timeout
from urllib3.util.retry import Retry

from .common import PaperRecord, clean_text, normalize_doi


SOURCE_NAME = "semantic_scholar"
DISPLAY_NAME = "Semantic Scholar"

S2_API_KEY = ""
LIMIT_PER_QUERY = 100
SLEEP_EACH_REQ = 2

FIELDS = ",".join([
    "paperId",
    "title",
    "authors",
    "abstract",
    "year",
    "venue",
    "publicationDate",
    "citationCount",
    "url",
    "externalIds",
])

REQUEST_TIMEOUT = (20, 60)
MAX_RETRY_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


def resolve_api_key(api_key: str | None = None) -> str:
    return (api_key or os.getenv("S2_API_KEY") or S2_API_KEY or "").strip()


def build_s2_session(api_key: str | None = None) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRY_ATTEMPTS - 1,
        connect=MAX_RETRY_ATTEMPTS - 1,
        read=MAX_RETRY_ATTEMPTS - 1,
        status=MAX_RETRY_ATTEMPTS - 1,
        backoff_factor=1.5,
        status_forcelist=RETRYABLE_STATUS_CODES,
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "Accept": "application/json",
        "Connection": "close",
        "User-Agent": "AiResearchDaily/1.0",
    })
    if api_key:
        session.headers["x-api-key"] = api_key
    return session


def is_retryable_ssl_error(exc: SSLError) -> bool:
    message = str(exc).lower()
    return (
        "unexpected eof while reading" in message
        or "eof occurred in violation of protocol" in message
        or "ssleoferror" in message
    )


def search_raw(
    query: str,
    limit: int,
    api_key: str | None = None,
    logger: Callable[[str], None] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    from .common import date_in_range

    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    resolved_api_key = resolve_api_key(api_key)
    params = {
        "query": query,
        "limit": min(max(limit * 5, limit), 1000) if (start_date or end_date) else limit,
        "fields": FIELDS,
        "sort": "publicationDate:desc",
    }

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        session = build_s2_session(resolved_api_key)
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json().get("data", [])
            if start_date or end_date:
                data = [
                    paper for paper in data
                    if date_in_range(clean_text(paper.get("publicationDate")) or clean_text(paper.get("year")), start_date, end_date)
                ]
            return data[:limit]
        except HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRY_ATTEMPTS:
                raise RuntimeError(f"Semantic Scholar API 请求失败，HTTP {status_code}。") from exc
        except SSLError as exc:
            last_error = exc
            if not is_retryable_ssl_error(exc) or attempt == MAX_RETRY_ATTEMPTS:
                raise RuntimeError(
                    "Semantic Scholar API TLS 连接异常，多次重试后仍失败。"
                    "这通常是网络抖动或服务端提前断开连接导致的。"
                ) from exc
        except (Timeout, ConnectionError) as exc:
            last_error = exc
            if attempt == MAX_RETRY_ATTEMPTS:
                raise RuntimeError("Semantic Scholar API 连接超时或中断，多次重试后仍失败。") from exc
        finally:
            session.close()

        wait_seconds = min(2 ** (attempt - 1), 8)
        message = f"[S2] 请求失败，第 {attempt}/{MAX_RETRY_ATTEMPTS} 次重试将在 {wait_seconds}s 后进行: {query}"
        print(message)
        if logger:
            logger(message)
        time.sleep(wait_seconds)

    raise RuntimeError("Semantic Scholar API 请求失败。") from last_error


def search_records(
    query: str,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
    api_key: str = "",
    logger: Callable[[str], None] | None = None,
    **_: object,
) -> list[PaperRecord]:
    raw_items = search_raw(
        query=query,
        limit=limit,
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
        logger=logger,
    )
    records: list[PaperRecord] = []
    for item in raw_items:
        external_ids = item.get("externalIds") or {}
        doi = normalize_doi(external_ids.get("DOI") or external_ids.get("doi") or "")
        authors = item.get("authors") or []
        author_names = [clean_text(author.get("name")) for author in authors if clean_text(author.get("name"))]
        institution_names = sorted({
            affiliation
            for author in authors
            for raw_affiliation in (author.get("affiliations") or [])
            if (affiliation := clean_text(raw_affiliation))
        })
        paper_id = clean_text(item.get("paperId"))
        records.append(PaperRecord(
            query=query,
            paperId=paper_id,
            source=SOURCE_NAME,
            title=clean_text(item.get("title")),
            authors="; ".join(author_names),
            institutions="; ".join(institution_names),
            abstract=clean_text(item.get("abstract")),
            year=clean_text(item.get("year")),
            venue=clean_text(item.get("venue")),
            publicationDate=clean_text(item.get("publicationDate")),
            citationCount=clean_text(item.get("citationCount")),
            doi=doi,
            url=clean_text(item.get("url")),
            source_ids={SOURCE_NAME: paper_id} if paper_id else {},
            external_ids=external_ids,
        ))
    return records


def record_from_item(item: dict) -> PaperRecord:
    external_ids = item.get("externalIds") or {}
    doi = normalize_doi(external_ids.get("DOI") or external_ids.get("doi") or "")
    authors = item.get("authors") or []
    author_names = [clean_text(author.get("name")) for author in authors if clean_text(author.get("name"))]
    institution_names = sorted({
        affiliation
        for author in authors
        for raw_affiliation in (author.get("affiliations") or [])
        if (affiliation := clean_text(raw_affiliation))
    })
    paper_id = clean_text(item.get("paperId"))
    return PaperRecord(
        paperId=paper_id,
        source=SOURCE_NAME,
        title=clean_text(item.get("title")),
        authors="; ".join(author_names),
        institutions="; ".join(institution_names),
        abstract=clean_text(item.get("abstract")),
        year=clean_text(item.get("year")),
        venue=clean_text(item.get("venue")),
        publicationDate=clean_text(item.get("publicationDate")),
        citationCount=clean_text(item.get("citationCount")),
        doi=doi,
        url=clean_text(item.get("url")),
        source_ids={SOURCE_NAME: paper_id} if paper_id else {},
        external_ids=external_ids,
    )


def fetch_by_doi(doi: str, api_key: str = "", logger: Callable[[str], None] | None = None) -> PaperRecord | None:
    doi = normalize_doi(doi)
    if not doi:
        return None
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
    params = {"fields": FIELDS}
    resolved_api_key = resolve_api_key(api_key)
    try:
        session = build_s2_session(resolved_api_key)
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        item = response.json()
        return record_from_item(item) if item else None
    except Exception as exc:
        if logger:
            logger(f"[semantic_scholar] DOI 回查失败 {doi}: {exc}")
        return None
    finally:
        try:
            session.close()
        except Exception:
            pass
