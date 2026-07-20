#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import time
from datetime import date
from typing import Any, Callable

import requests

from .common import PaperRecord, REQUEST_TIMEOUT, clean_text, date_in_range, normalize_doi, year_from_date


SOURCE_NAME = "springer_nature"
DISPLAY_NAME = "Springer Nature Open Access"

OPENACCESS_BASE_URL = os.getenv(
    "SPRINGER_OPENACCESS_API_BASE_URL",
    "https://api.springernature.com/openaccess/json",
).strip()
META_BASE_URL = os.getenv("SPRINGER_META_API_BASE_URL", "https://api.springernature.com/meta/v2/json").strip()
API_KEY_PARAM = os.getenv("SPRINGER_OPENACCESS_API_KEY_PARAM", os.getenv("SPRINGER_META_API_KEY_PARAM", "api_key")).strip() or "api_key"
QUERY_PARAM = os.getenv("SPRINGER_OPENACCESS_QUERY_PARAM", os.getenv("SPRINGER_META_QUERY_PARAM", "q")).strip() or "q"
PAGE_SIZE_PARAM = os.getenv("SPRINGER_OPENACCESS_PAGE_SIZE_PARAM", os.getenv("SPRINGER_META_PAGE_SIZE_PARAM", "p")).strip() or "p"
START_PARAM = os.getenv("SPRINGER_OPENACCESS_START_PARAM", os.getenv("SPRINGER_META_START_PARAM", "s")).strip() or "s"
RECORDS_KEY = os.getenv("SPRINGER_OPENACCESS_RECORDS_KEY", os.getenv("SPRINGER_META_RECORDS_KEY", "records")).strip() or "records"
PAGE_SIZE = int(os.getenv("SPRINGER_OPENACCESS_PAGE_SIZE", os.getenv("SPRINGER_META_PAGE_SIZE", "25")))
MAX_PAGES = int(os.getenv("SPRINGER_OPENACCESS_MAX_PAGES", os.getenv("SPRINGER_META_MAX_PAGES", "20")))
MAX_RETRIES = int(os.getenv("SPRINGER_OPENACCESS_MAX_RETRIES", os.getenv("SPRINGER_META_MAX_RETRIES", "3")))
RETRY_SLEEP_SECONDS = float(os.getenv("SPRINGER_OPENACCESS_RETRY_SLEEP", os.getenv("SPRINGER_META_RETRY_SLEEP", "2.0")))
REQUEST_INTERVAL_SECONDS = float(os.getenv("SPRINGER_OPENACCESS_REQUEST_INTERVAL", os.getenv("SPRINGER_META_REQUEST_INTERVAL", "1.2")))
LAST_REQUEST_AT = 0.0


def normalize_api_type(value: str | None = None) -> str:
    text = clean_text(value or os.getenv("SPRINGER_NATURE_API_TYPE") or os.getenv("SPRINGER_API_TYPE") or "openaccess").lower()
    text = text.replace("-", "_").replace(" ", "_")
    if text in {"meta", "metadata", "meta_api"}:
        return "meta"
    return "openaccess"


def base_url_for_api(api_type: str | None = None) -> str:
    return META_BASE_URL if normalize_api_type(api_type) == "meta" else OPENACCESS_BASE_URL


def resolve_api_key(api_key: str | None = None) -> str:
    return (
        api_key
        or os.getenv("SPRINGER_OPENACCESS_API_KEY")
        or os.getenv("SPRINGER_META_API_KEY")
        or os.getenv("META_API_KEY")
        or os.getenv("SPRINGER_API_KEY")
        or ""
    ).strip()


def build_query(query: str) -> str:
    return clean_text(query)


def wait_for_rate_limit() -> None:
    global LAST_REQUEST_AT
    now = time.monotonic()
    elapsed = now - LAST_REQUEST_AT if LAST_REQUEST_AT else REQUEST_INTERVAL_SECONDS
    if elapsed < REQUEST_INTERVAL_SECONDS:
        time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
    LAST_REQUEST_AT = time.monotonic()


def fetch_page(
    session: requests.Session,
    query: str,
    page: int,
    page_size: int,
    api_key: str,
    api_type: str = "openaccess",
) -> dict[str, Any]:
    start = (page - 1) * page_size + 1
    params: dict[str, Any] = {
        QUERY_PARAM: query,
        PAGE_SIZE_PARAM: page_size,
        START_PARAM: start,
    }
    if api_key:
        params[API_KEY_PARAM] = api_key

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            wait_for_rate_limit()
            response = session.get(base_url_for_api(api_type), params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code in {401, 403}:
                body = response.text.strip()[:300]
                api_label = "Meta API" if normalize_api_type(api_type) == "meta" else "Open Access API"
                raise RuntimeError(f"Springer Nature {api_label} 认证或权限失败（HTTP {response.status_code}）：{body}")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP_SECONDS * attempt)
    api_label = "Meta API" if normalize_api_type(api_type) == "meta" else "Open Access API"
    raise RuntimeError(f"Springer Nature {api_label} 请求失败：{last_error}")


def get_first_str(record: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [flatten_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        preferred_keys = ["p", "abstract", "text", "content", "summary"]
        parts = [flatten_text(value.get(key)) for key in preferred_keys if key in value]
        for key, item in value.items():
            if key in preferred_keys or key == "h1":
                continue
            parts.append(flatten_text(item))
        seen = set()
        deduped = []
        for part in parts:
            if not part or part in seen:
                continue
            seen.add(part)
            deduped.append(part)
        return "\n".join(deduped)
    return ""


def extract_abstract(record: dict[str, Any]) -> str:
    for key in ["abstract", "summary", "description"]:
        if key in record:
            return flatten_text(record.get(key))
    return ""


def extract_authors(record: dict[str, Any]) -> str:
    author_items = None
    for key in ["creators", "authors", "author"]:
        value = record.get(key)
        if isinstance(value, list):
            author_items = value
            break

    names: list[str] = []
    if author_items:
        for item in author_items:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict):
                name = (
                    get_first_str(item, ["creator", "author", "name", "displayName", "fullname", "fullName"])
                    or " ".join(
                        part
                        for part in [
                            get_first_str(item, ["givenName", "firstName"]),
                            get_first_str(item, ["familyName", "lastName", "surname"]),
                        ]
                        if part
                    ).strip()
                )
            else:
                name = ""
            if name and name not in names:
                names.append(name)

    if not names:
        for key in ["creator", "author", "authors"]:
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "; ".join(names)


def get_links(record: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for key in ["url", "urls", "link", "links"]:
        value = record.get(key, [])
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    links.append({
                        "format": str(item.get("format", "")),
                        "value": str(item.get("value", "") or item.get("url", "")),
                    })
    return links


def pick_link(links: list[dict[str, str]], target: str) -> str:
    target = target.lower()
    for item in links:
        fmt = item.get("format", "").lower()
        val = item.get("value", "")
        lowered = val.lower()
        if target in fmt:
            return val
        if target == "xml" and lowered.endswith(".xml"):
            return val
        if target == "pdf" and lowered.endswith(".pdf"):
            return val
        if target == "html" and (".html" in lowered or ".htm" in lowered or "fulltext" in lowered):
            return val
    return ""


def record_to_paper(record: dict[str, Any], query: str) -> PaperRecord:
    doi = normalize_doi(get_first_str(record, ["doi", "identifier"]))
    title = clean_text(get_first_str(record, ["title"]))
    publication_date = clean_text(get_first_str(record, ["publicationDate", "coverDate", "date"]))
    journal = clean_text(get_first_str(record, ["publicationName", "journal", "source", "publication"]))
    links = get_links(record)
    pdf_url = pick_link(links, "pdf")
    html_url = pick_link(links, "html")
    xml_url = pick_link(links, "xml") or pick_link(links, "jats")

    return PaperRecord(
        query=query,
        paperId=doi or title,
        source=SOURCE_NAME,
        title=title,
        authors=clean_text(extract_authors(record)),
        abstract=clean_text(extract_abstract(record)),
        year=year_from_date(publication_date),
        venue=journal,
        publicationDate=publication_date,
        doi=doi,
        url=html_url or (f"https://doi.org/{doi}" if doi else ""),
        pdf_url=pdf_url,
        source_ids={SOURCE_NAME: doi} if doi else {},
        external_ids={
            "DOI": doi,
            "xml_url": xml_url,
            "html_url": html_url,
            "links": links,
            "raw_source": DISPLAY_NAME,
        },
    )


def search_records(
    query: str,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
    api_key: str = "",
    api_type: str = "openaccess",
    logger: Callable[[str], None] | None = None,
    **_: object,
) -> list[PaperRecord]:
    resolved_api_key = resolve_api_key(api_key)
    resolved_api_type = normalize_api_type(api_type)
    api_label = "Meta API" if resolved_api_type == "meta" else "Open Access API"
    if not resolved_api_key:
        raise RuntimeError(
            f"Springer Nature {api_label} 需要 API Key，请填写 Springer Nature API Key "
            "或设置 SPRINGER_OPENACCESS_API_KEY / SPRINGER_META_API_KEY。"
        )

    session = requests.Session()
    session.headers.update({
        "User-Agent": "AiResearchDaily/1.0",
        "Accept": "application/json, */*",
    })
    resolved_query = build_query(query)
    page_size = min(max(limit, 1), PAGE_SIZE)
    records: list[PaperRecord] = []
    seen: set[str] = set()

    page = 1
    while len(records) < limit and page <= MAX_PAGES:
        data = fetch_page(session, resolved_query, page, page_size, resolved_api_key, api_type=resolved_api_type)
        raw_records = data.get(RECORDS_KEY, [])
        if not isinstance(raw_records, list) or not raw_records:
            break

        for raw in raw_records:
            if not isinstance(raw, dict):
                continue
            item = record_to_paper(raw, query=query)
            if not date_in_range(item.publicationDate or item.year, start_date, end_date):
                continue
            key = item.doi or item.title.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            records.append(item)
            if len(records) >= limit:
                break

        if len(raw_records) < page_size:
            break
        page += 1

    if logger:
        logger(f"[springer_nature] api={resolved_api_type}, query={resolved_query}, records={len(records)}")
    return records


def fetch_by_doi(
    doi: str,
    api_key: str = "",
    api_type: str = "openaccess",
    logger: Callable[[str], None] | None = None,
) -> PaperRecord | None:
    doi = normalize_doi(doi)
    if not doi:
        return None
    matches = search_records(
        query=f'doi:"{doi}"',
        limit=1,
        api_key=api_key,
        api_type=api_type,
        logger=logger,
    )
    for match in matches:
        if normalize_doi(match.doi) == doi:
            return match
    return matches[0] if matches else None
