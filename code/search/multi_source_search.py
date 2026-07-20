#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    CODE_DIR = Path(sys._MEIPASS)
    PROJECT_DIR = Path(sys.executable).resolve().parent
else:
    CODE_DIR = Path(__file__).resolve().parents[1]
    PROJECT_DIR = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from data_sources import ALL_SOURCES, DEFAULT_SOURCES, get_source, selected_sources_or_default
from data_sources import crossref, openalex
from data_sources.common import (
    OUTPUT_COLUMNS,
    PaperRecord,
    clean_text,
    normalize_doi,
    normalize_title_key,
    parse_date_input,
    sanitize_query_name,
)
from search import literature_store

try:
    from domain import materials_vocab
except ImportError:
    materials_vocab = None


def log_message(message: str, logger: Callable[[str], None] | None = None) -> None:
    print(message)
    if logger:
        logger(message)


def normalize_credentials(credentials: dict[str, Any] | None = None) -> dict[str, str]:
    credentials = credentials or {}
    return {
        "semantic_scholar_api_key": clean_text(credentials.get("semantic_scholar_api_key")),
        "openalex_email": clean_text(credentials.get("openalex_email")),
        "crossref_email": clean_text(credentials.get("crossref_email")),
        "pubmed_api_key": clean_text(credentials.get("pubmed_api_key")),
        "pubmed_email": clean_text(credentials.get("pubmed_email")),
        "springer_nature_api_key": clean_text(credentials.get("springer_nature_api_key")),
        "springer_nature_api_type": clean_text(credentials.get("springer_nature_api_type")) or "openaccess",
    }


def metadata_output_dirs(output_dir: str | Path) -> tuple[Path, Path]:
    output_path = Path(output_dir)
    if output_path.name == "metadata" or (output_path / "csv").exists() or (output_path / "json").exists():
        csv_dir = output_path / "csv"
        json_dir = output_path / "json"
        csv_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)
        return csv_dir, json_dir
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path, output_path


def search_source(
    source: str,
    query: str,
    limit: int,
    api_key: str,
    start_date,
    end_date,
    logger: Callable[[str], None] | None = None,
    source_credentials: dict[str, Any] | None = None,
) -> list[PaperRecord]:
    credentials = normalize_credentials(source_credentials)
    source_module = get_source(source)
    if source == "semantic_scholar":
        return source_module.search_records(
            query=query,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            api_key=credentials.get("semantic_scholar_api_key") or api_key,
            logger=logger,
        )
    if source == "openalex":
        return source_module.search_records(
            query=query,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            contact_email=credentials.get("openalex_email", ""),
        )
    if source == "crossref":
        return source_module.search_records(
            query=query,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            contact_email=credentials.get("crossref_email", ""),
        )
    if source == "pubmed":
        return source_module.search_records(
            query=query,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            api_key=credentials.get("pubmed_api_key", ""),
            contact_email=credentials.get("pubmed_email", ""),
        )
    if source == "springer_nature":
        if not credentials.get("springer_nature_api_key"):
            api_type = credentials.get("springer_nature_api_type", "openaccess")
            api_label = "Meta API" if api_type == "meta" else "Open Access API"
            log_message(f"[springer_nature] 跳过：Springer Nature {api_label} 需要 API Key。", logger)
            return []
        return source_module.search_records(
            query=query,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            api_key=credentials.get("springer_nature_api_key", ""),
            api_type=credentials.get("springer_nature_api_type", "openaccess"),
            logger=logger,
        )
    return source_module.search_records(
        query=query,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )


def choose_better_value(current: str, candidate: str, prefer_longer: bool = False) -> str:
    current = clean_text(current)
    candidate = clean_text(candidate)
    if not current:
        return candidate
    if prefer_longer and len(candidate) > len(current) * 1.2:
        return candidate
    return current


def merge_record(base: PaperRecord, candidate: PaperRecord, enrichment_source: str | None = None) -> PaperRecord:
    base.title = choose_better_value(base.title, candidate.title)
    base.authors = choose_better_value(base.authors, candidate.authors)
    base.abstract = choose_better_value(base.abstract, candidate.abstract, prefer_longer=True)
    base.year = choose_better_value(base.year, candidate.year)
    base.venue = choose_better_value(base.venue, candidate.venue)
    base.volume = choose_better_value(base.volume, candidate.volume)
    base.issue = choose_better_value(base.issue, candidate.issue)
    base.publicationDate = choose_better_value(base.publicationDate, candidate.publicationDate)
    base.citationCount = choose_better_value(base.citationCount, candidate.citationCount)
    base.doi = normalize_doi(base.doi) or normalize_doi(candidate.doi)
    base.url = choose_better_value(base.url, candidate.url)
    base.pdf_url = choose_better_value(base.pdf_url, candidate.pdf_url)
    base.source_ids.update({k: v for k, v in candidate.source_ids.items() if v})
    base.external_ids.update({k: v for k, v in candidate.external_ids.items() if v})
    if enrichment_source:
        base.enrichment_sources.add(enrichment_source)
    elif candidate.source and candidate.source != base.source:
        base.enrichment_sources.add(candidate.source)
    return base


def merge_records(records: Iterable[PaperRecord]) -> list[PaperRecord]:
    merged: dict[str, PaperRecord] = {}
    order: list[str] = []
    for record in records:
        record.doi = normalize_doi(record.doi)
        key = f"doi:{record.doi}" if record.doi else f"title:{normalize_title_key(record.title)}"
        if key.endswith(":"):
            key = f"source:{record.source}:{record.paperId or len(order)}"
        if key not in merged:
            merged[key] = record
            order.append(key)
        else:
            merge_record(merged[key], record)
    return [merged[key] for key in order]


def needs_metadata_enrichment(record: PaperRecord) -> bool:
    return not (
        clean_text(record.venue)
        and clean_text(record.abstract)
        and clean_text(record.publicationDate)
        and clean_text(record.citationCount)
    )


def fetch_source_by_doi(
    source: str,
    doi: str,
    credentials: dict[str, Any],
    logger: Callable[[str], None] | None = None,
) -> PaperRecord | None:
    source_module = get_source(source)
    fetcher = getattr(source_module, "fetch_by_doi", None)
    if not fetcher:
        return None
    try:
        if source == "semantic_scholar":
            return fetcher(
                doi,
                api_key=credentials.get("semantic_scholar_api_key", ""),
                logger=logger,
            )
        if source == "openalex":
            return fetcher(doi, contact_email=credentials.get("openalex_email", ""))
        if source == "crossref":
            return fetcher(doi, contact_email=credentials.get("crossref_email", ""))
        if source == "pubmed":
            return fetcher(
                doi,
                api_key=credentials.get("pubmed_api_key", ""),
                contact_email=credentials.get("pubmed_email", ""),
            )
        if source == "springer_nature":
            if not credentials.get("springer_nature_api_key"):
                api_type = credentials.get("springer_nature_api_type", "openaccess")
                api_label = "Meta API" if api_type == "meta" else "Open Access API"
                log_message(f"[springer_nature] DOI 回查跳过 {doi}: 缺少 {api_label} Key。", logger)
                return None
            return fetcher(
                doi,
                api_key=credentials.get("springer_nature_api_key", ""),
                api_type=credentials.get("springer_nature_api_type", "openaccess"),
                logger=logger,
            )
        return fetcher(doi)
    except Exception as exc:
        log_message(f"[WARN] {source} DOI 回查失败 {doi}: {exc}", logger)
        return None


def filter_records_by_materials_relevance(
    records: list[PaperRecord],
    *,
    min_score: int = 1,
    logger: Callable[[str], None] | None = None,
) -> list[PaperRecord]:
    """
    使用材料科学词表库过滤文献记录，剔除与材料科学无关的文献。

    通过检查标题和摘要中是否包含材料科学相关术语来判断相关性。
    """
    if materials_vocab is None or not records:
        return records

    kept: list[PaperRecord] = []
    removed_count = 0
    for record in records:
        combined_text = " ".join([
            str(getattr(record, "title", "") or ""),
            str(getattr(record, "abstract", "") or ""),
        ])
        if materials_vocab.is_materials_science_related(combined_text, min_score=min_score):
            kept.append(record)
        else:
            removed_count += 1

    if removed_count > 0:
        log_message(
            f"[VocabFilter] 过滤掉 {removed_count} 条与材料科学无关的文献，保留 {len(kept)} 条",
            logger,
        )
    return kept


def enrich_records(
    records: list[PaperRecord],
    sources: Iterable[str] | None = None,
    source_credentials: dict[str, Any] | None = None,
    logger: Callable[[str], None] | None = None,
    sleep_each_req: float = 0.0,
) -> list[PaperRecord]:
    enrich_sources = selected_sources_or_default(sources)
    credentials = normalize_credentials(source_credentials)

    for idx, record in enumerate(records, 1):
        doi = normalize_doi(record.doi)
        if doi:
            log_message(f"[Enrich] DOI 回查 {idx}/{len(records)}: {doi}", logger)
            for source in enrich_sources:
                if source == "arxiv":
                    continue
                if not needs_metadata_enrichment(record) and record.volume and record.issue and record.pdf_url:
                    break
                candidate = fetch_source_by_doi(source, doi, credentials, logger)
                if candidate:
                    merge_record(record, candidate, source)
        elif record.title:
            title_query = record.title[:180]
            if "crossref" in enrich_sources:
                try:
                    matches = crossref.search_records(title_query, 1, contact_email=credentials.get("crossref_email", ""))
                    if matches:
                        merge_record(record, matches[0], "crossref")
                except Exception:
                    pass
            if "openalex" in enrich_sources and (not record.abstract or not record.citationCount):
                try:
                    matches = openalex.search_records(title_query, 1, contact_email=credentials.get("openalex_email", ""))
                    if matches:
                        merge_record(record, matches[0], "openalex")
                except Exception:
                    pass
        if sleep_each_req > 0 and idx < len(records):
            time.sleep(sleep_each_req)
    return records


def write_records(records: list[PaperRecord], jsonl_path: Path, csv_path: Path) -> None:
    rows = [record.to_row() for record in records]
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    df = pd.DataFrame(rows)
    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df[OUTPUT_COLUMNS].to_csv(csv_path, index=False, encoding="utf-8-sig")


def search_and_save_queries(
    queries: Iterable[str],
    limit: int,
    sleep_each_req: float,
    api_key: str,
    output_dir: str | Path,
    selected_sources: Iterable[str] | None = None,
    source_credentials: dict[str, Any] | None = None,
    report_date: str | None = None,
    logger: Callable[[str], None] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    enrich_missing: bool = True,
    filter_materials: bool = True,
    persist_library: bool = False,
) -> list[dict[str, Any]]:
    sources = selected_sources_or_default(selected_sources)
    credentials = normalize_credentials(source_credentials)
    if api_key and not credentials.get("semantic_scholar_api_key"):
        credentials["semantic_scholar_api_key"] = api_key
    clean_queries = [clean_text(query) for query in queries if clean_text(query)]
    if not clean_queries:
        raise ValueError("至少需要一个有效的检索词。")

    start = parse_date_input(start_date)
    end = parse_date_input(end_date)
    if start and end and start > end:
        raise ValueError("起始日期不能晚于结束日期。")

    output_path = Path(output_dir)
    csv_output_dir, json_output_dir = metadata_output_dirs(output_path)
    active_date = report_date or datetime.now().strftime("%Y-%m-%d")
    per_query_outputs: list[dict[str, Any]] = []

    for query in clean_queries:
        all_records: list[PaperRecord] = []
        log_message(f"[MultiSource] query: {query}", logger)
        log_message(f"[MultiSource] sources: {', '.join(sources)}", logger)
        for source in sources:
            try:
                records = search_source(source, query, limit, api_key, start, end, logger, credentials)
                log_message(f"[{source}] {len(records)} papers", logger)
                all_records.extend(records)
            except Exception as exc:
                log_message(f"[WARN] {source} 检索失败：{exc}", logger)
            if sleep_each_req > 0:
                time.sleep(sleep_each_req)

        merged = merge_records(all_records)

        # 使用材料科学词表库过滤无关文献（在补全前过滤，可减少 API 调用）
        if filter_materials and materials_vocab is not None and merged:
            log_message("[MultiSource] 使用材料科学词表库过滤无关文献", logger)
            merged = filter_records_by_materials_relevance(merged, logger=logger)

        if enrich_missing and merged:
            log_message("[MultiSource] 开始补全 DOI、期刊、摘要和引用数", logger)
            enrich_records(merged, sources=sources, source_credentials=credentials, logger=logger, sleep_each_req=0)

        safe_topic = sanitize_query_name(query)
        jsonl_path = json_output_dir / f"{safe_topic}_{active_date}.jsonl"
        csv_path = csv_output_dir / f"{safe_topic}_{active_date}.csv"
        write_records(merged, jsonl_path, csv_path)
        output_item = {
            "query": query,
            "count": len(merged),
            "jsonl_path": jsonl_path,
            "csv_path": csv_path,
            "library_persisted": False,
            "sources": sources,
        }
        if persist_library:
            run_id = f"search_{safe_topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            store_result = literature_store.upsert_records(
                merged,
                output_dir=output_path,
                run_id=run_id,
                query=query,
                run_type="search",
                sources=sources,
                csv_path=csv_path,
                jsonl_path=jsonl_path,
            )
            log_message(
                "[Library] 持续文献库已更新: "
                f"新增 {store_result['inserted']} 条，更新 {store_result['updated']} 条，"
                f"库文件 {store_result['db_path']}",
                logger,
            )
            output_item.update({
                "library_db_path": store_result["db_path"],
                "library_inserted": store_result["inserted"],
                "library_updated": store_result["updated"],
                "library_persisted": True,
            })
        else:
            log_message("[Library] CSV 已生成，未自动入库；请在文献预览中手动点击入库。", logger)
        per_query_outputs.append(output_item)

    log_message("", logger)
    log_message("Done.", logger)
    for item in per_query_outputs:
        log_message(f"- {item['query']} -> {item['count']} papers", logger)
        log_message(f"  CSV  : {item['csv_path']}", logger)
    return per_query_outputs


METADATA_FIELD_ALIASES = {
    "query": ("query", "keyword", "keywords", "检索词", "关键词"),
    "paperId": ("paperId", "paper_id", "id", "文献id", "文献编号"),
    "source": ("source", "database", "来源", "数据源"),
    "title": ("title", "paper_title", "article_title", "题目", "标题", "文献标题"),
    "authors": ("authors", "author", "creator", "作者", "作者列表"),
    "institutions": ("institutions", "institution", "affiliations", "affiliation", "机构", "作者单位"),
    "abstract": ("abstract", "summary", "摘要", "文摘"),
    "year": ("year", "publication_year", "published_year", "年份", "发表年份", "出版年份"),
    "venue": ("venue", "journal", "publication", "期刊", "刊名", "出版物"),
    "volume": ("volume", "卷", "卷号"),
    "issue": ("issue", "期", "期号"),
    "publicationDate": (
        "publicationDate", "publication_date", "published", "published_date", "date",
        "发表时间", "发表日期", "出版日期",
    ),
    "citationCount": ("citationCount", "citation_count", "citations", "cited_by", "引用", "引用数"),
    "doi": ("doi", "DOI"),
    "url": ("url", "link", "article_url", "网页", "网址", "链接"),
    "pdf_url": ("pdf_url", "pdfUrl", "pdf", "pdf_link", "PDF链接", "全文链接"),
    "source_ids_json": ("source_ids_json", "source_ids", "来源标识"),
    "externalIds_json": ("externalIds_json", "external_ids", "外部标识"),
    "enrichment_sources": ("enrichment_sources", "补全来源"),
}


def _normalized_metadata_key(value: Any) -> str:
    return re.sub(r"[\s_\-]+", "", clean_text(value)).lower()


def _metadata_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "; ".join(clean_text(item) for item in value if clean_text(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return clean_text(value)


def _metadata_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(clean_text(value) or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def record_from_mapping(mapping: dict[str, Any], *, default_source: str = "manual") -> PaperRecord:
    normalized_mapping = {
        _normalized_metadata_key(key): value
        for key, value in mapping.items()
        if _normalized_metadata_key(key)
    }

    def field_value(field: str) -> Any:
        for alias in METADATA_FIELD_ALIASES[field]:
            key = _normalized_metadata_key(alias)
            if key in normalized_mapping:
                return normalized_mapping[key]
        return ""

    publication_date = _metadata_text(field_value("publicationDate"))
    year = _metadata_text(field_value("year"))
    if not year and re.match(r"^\d{4}", publication_date):
        year = publication_date[:4]
    enrichment_raw = field_value("enrichment_sources")
    if isinstance(enrichment_raw, (list, tuple, set)):
        enrichment_sources = {_metadata_text(item) for item in enrichment_raw if _metadata_text(item)}
    else:
        enrichment_sources = {
            item.strip()
            for item in re.split(r"[;,；，]+", _metadata_text(enrichment_raw))
            if item.strip()
        }
    return PaperRecord(
        query=_metadata_text(field_value("query")),
        paperId=_metadata_text(field_value("paperId")),
        source=_metadata_text(field_value("source")) or default_source,
        title=_metadata_text(field_value("title")),
        authors=_metadata_text(field_value("authors")),
        institutions=_metadata_text(field_value("institutions")),
        abstract=_metadata_text(field_value("abstract")),
        year=year,
        venue=_metadata_text(field_value("venue")),
        volume=_metadata_text(field_value("volume")),
        issue=_metadata_text(field_value("issue")),
        publicationDate=publication_date,
        citationCount=_metadata_text(field_value("citationCount")),
        doi=normalize_doi(field_value("doi")),
        url=_metadata_text(field_value("url")),
        pdf_url=_metadata_text(field_value("pdf_url")),
        source_ids=_metadata_json_dict(field_value("source_ids_json")),
        external_ids=_metadata_json_dict(field_value("externalIds_json")),
        enrichment_sources=enrichment_sources,
    )


def records_from_csv(csv_path: str | Path) -> list[PaperRecord]:
    df = pd.read_csv(csv_path)
    return [
        record_from_mapping(row.to_dict(), default_source="csv")
        for _, row in df.fillna("").iterrows()
    ]


def records_from_json(json_path: str | Path) -> list[PaperRecord]:
    path = Path(json_path)
    if path.suffix.lower() == ".jsonl":
        payload = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    else:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        for key in ("papers", "records", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        raise ValueError("JSON 顶层必须是文献对象、文献数组，或包含 papers/records/items/data/results 数组")
    return [
        record_from_mapping(item, default_source="json")
        for item in payload
        if isinstance(item, dict)
    ]


def enrich_csv_file(
    input_csv: str | Path,
    output_dir: str | Path,
    selected_sources: Iterable[str] | None = None,
    source_credentials: dict[str, Any] | None = None,
    logger: Callable[[str], None] | None = None,
    filter_materials: bool = True,
    persist_library: bool = False,
) -> dict[str, Any]:
    source_path = Path(input_csv)
    records = merge_records(records_from_csv(source_path))
    log_message(f"[Enrich] 读取 {len(records)} 条文献，开始多源补全", logger)

    # 使用材料科学词表库过滤无关文献
    if filter_materials and materials_vocab is not None and records:
        log_message("[Enrich] 使用材料科学词表库过滤无关文献", logger)
        records = filter_records_by_materials_relevance(records, logger=logger)

    enrich_records(records, sources=selected_sources, source_credentials=source_credentials, logger=logger, sleep_each_req=0)
    output_path = Path(output_dir)
    csv_output_dir, json_output_dir = metadata_output_dirs(output_path)
    target_stem = f"{source_path.stem}_enriched_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    target_csv = csv_output_dir / f"{target_stem}.csv"
    target_jsonl = json_output_dir / f"{target_stem}.jsonl"
    write_records(records, target_jsonl, target_csv)
    output_item = {
        "csv_path": target_csv,
        "jsonl_path": target_jsonl,
        "count": len(records),
        "library_persisted": False,
    }
    if persist_library:
        store_result = literature_store.upsert_records(
            records,
            output_dir=output_path,
            run_id=f"enrich_{source_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            query=source_path.stem,
            run_type="enrich",
            sources=selected_sources_or_default(selected_sources),
            csv_path=target_csv,
            jsonl_path=target_jsonl,
        )
        log_message(
            "[Library] 持续文献库已更新: "
            f"新增 {store_result['inserted']} 条，更新 {store_result['updated']} 条，"
            f"库文件 {store_result['db_path']}",
            logger,
        )
        output_item.update({
            "library_db_path": store_result["db_path"],
            "library_inserted": store_result["inserted"],
            "library_updated": store_result["updated"],
            "library_persisted": True,
        })
    else:
        log_message("[Library] 补全 CSV 已生成，未自动入库；请在文献预览中手动点击入库。", logger)
    log_message(f"[Enrich] 补全完成: {target_csv}", logger)
    return output_item
