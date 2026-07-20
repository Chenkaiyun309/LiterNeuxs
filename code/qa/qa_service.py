#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from typing import Any, Callable

from qa import citation_validator, prompt_builder, retriever


class QaServiceError(RuntimeError):
    """Raised when QA generation fails."""


ANSWER_FIELD_RE = re.compile(r'"answer"\s*:\s*"')
DISPLAY_FORMULA_RE = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.DOTALL)
FORMULA_QUESTION_RE = re.compile(r"公式|方程|表达式|计算式|equation|formula", re.IGNORECASE)
FOLLOW_UP_RE = re.compile(r"这个|上述|对应|相关|其中|它们?|进一步|继续|公式|图片|图表|为什么|如何", re.IGNORECASE)


def _parse_json_payload(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise QaServiceError("模型未返回内容")
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        text = text[first:last + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QaServiceError(f"模型输出不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise QaServiceError("模型输出不是对象 JSON")
    return payload


def _decode_partial_json_string(text: str, start: int) -> str:
    output: list[str] = []
    index = start
    escapes = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    while index < len(text):
        char = text[index]
        if char == '"':
            break
        if char != "\\":
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(text):
            output.append("\\")
            break
        escaped = text[index + 1]
        if escaped == "u" and index + 5 < len(text):
            codepoint = text[index + 2:index + 6]
            try:
                output.append(chr(int(codepoint, 16)))
                index += 6
                continue
            except ValueError:
                pass
        if escaped in escapes:
            output.append(escapes[escaped])
        else:
            # Preserve unescaped LaTeX commands such as \frac rather than dropping the slash.
            output.extend(("\\", escaped))
        index += 2
    return "".join(output).strip()


def _recover_partial_payload(raw_text: str, allowed_source_ids: list[str]) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    match = ANSWER_FIELD_RE.search(text)
    if match:
        answer = _decode_partial_json_string(text, match.end())
    else:
        answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    if len(answer) < 20:
        return None
    if answer.count("$$") % 2:
        answer = answer[:answer.rfind("$$")].rstrip()
        answer += "\n\n> 回答达到模型输出上限，末尾未完成的公式已省略。"
    if answer.count("\\[") > answer.count("\\]"):
        answer = answer[:answer.rfind("\\[")].rstrip()
        answer += "\n\n> 回答达到模型输出上限，末尾未完成的公式已省略。"

    cited_orders: list[int] = []
    for value in citation_validator.extract_citation_orders(answer):
        if 1 <= value <= len(allowed_source_ids) and value not in cited_orders:
            cited_orders.append(value)

    order_map = {original: index for index, original in enumerate(cited_orders, 1)}
    if order_map:
        answer = re.sub(
            r"\[(\d+)\]",
            lambda item: f"[{order_map[int(item.group(1))]}]" if int(item.group(1)) in order_map else item.group(0),
            answer,
        )
    citations = [
        {
            "citation_order": order_map[original],
            "chunk_id": allowed_source_ids[original - 1],
            "claim": "支持回答中对应编号的结论",
        }
        for original in cited_orders
    ]
    return {
        "answer": answer,
        "citations": citations,
        "insufficient_evidence": "现有文献证据不足" in answer or "现有全文证据不足" in answer,
    }


def _contextual_retrieval_question(question: str, conversation: list[dict[str, Any]] | None) -> str:
    current = str(question or "").strip()
    if not conversation or (len(current) > 100 and not FOLLOW_UP_RE.search(current)):
        return current
    context_parts = []
    for item in reversed(conversation):
        content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        if not content or content.startswith(("请求未完成", "缺少待修复内容")):
            continue
        context_parts.append(content[:700])
        if len(context_parts) >= 3:
            break
    if not context_parts:
        return current
    context_parts.reverse()
    return f"{current}\n对话上下文：{' '.join(context_parts)}"


def _formula_context(text: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", str(text or ""))
    value = DISPLAY_FORMULA_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return "原文片段未提供额外的符号定义或适用条件。"
    sentences = re.split(r"(?<=[。！？.!?])\s+", value)
    selected = [
        sentence for sentence in sentences
        if re.search(r"其中|式中|表示|定义|适用|条件|where|denote|represent|respectively|defined", sentence, re.IGNORECASE)
    ]
    context = " ".join(selected[:3]) or value
    context = re.sub(r"\[(\d+)\]", r"(原文参考文献 \1)", context)
    return context[:600].rstrip()


def _formula_evidence_payload(question: str, evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not FORMULA_QUESTION_RE.search(str(question or "")):
        return None
    records: list[dict[str, Any]] = []
    seen_formulas: set[str] = set()
    for item in evidence:
        text = str(item.get("chunk_text") or "")
        formulas = []
        for match in DISPLAY_FORMULA_RE.finditer(text):
            formula = (match.group(1) or match.group(2) or "").strip()
            normalized = re.sub(r"\s+", "", formula)
            if not formula or normalized in seen_formulas:
                continue
            seen_formulas.add(normalized)
            formulas.append(formula[:1600])
            if len(formulas) >= 2:
                break
        if formulas:
            records.append({"item": item, "formulas": formulas, "context": _formula_context(text)})
        if len(records) >= 5:
            break
    if not records:
        return None

    answer_parts = [
        "## 文献中的相关计算公式",
        "云端模型本次未返回正文，以下内容直接从已解析的全文证据中提取。公式、符号定义和适用条件均以引用片段为准。",
    ]
    citations = []
    for order, record in enumerate(records, 1):
        item = record["item"]
        answer_parts.append(f"### 公式 {order}")
        answer_parts.extend(f"$${formula}$$" for formula in record["formulas"])
        answer_parts.append(f"**原文定义与适用上下文：** {record['context']} [{order}]")
        citations.append({
            "citation_order": order,
            "chunk_id": str(item.get("source_id") or item.get("chunk_id") or ""),
            "claim": "该全文片段包含所列公式及其相邻定义或适用上下文",
        })
    answer_parts.append("## 使用说明\n公式中的变量、单位和边界条件应按对应引用片段核对；证据未明确给出的含义不作推断。")
    return {
        "answer": "\n\n".join(answer_parts),
        "citations": citations,
        "insufficient_evidence": False,
    }


def _merge_token_usage(*items: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [item.get(key) for item in items if isinstance(item, dict)]
        numeric = [int(value) for value in values if isinstance(value, int)]
        merged[key] = sum(numeric) if numeric else None
    return merged


def select_single_paper_chunks(conn, *, identity_key: str, question: str, top_k: int = 8) -> list[dict[str, Any]]:
    query = retriever.fts_query(question)
    if not query:
        return []
    sql = """
        SELECT
            fts.chunk_id,
            fts.identity_key,
            fts.section_title,
            fts.chunk_text,
            bm25(paper_chunks_fts) AS bm25_score,
            c.page_start,
            c.page_end,
            COALESCE(c.chunk_index, 0) AS chunk_index,
            COALESCE(c.chunk_type, 'body') AS chunk_type,
            COALESCE(c.page_mapping_confidence, 0) AS page_mapping_confidence,
            COALESCE(c.token_count, 0) AS token_count
        FROM paper_chunks_fts fts
        JOIN paper_chunks c ON c.chunk_id = fts.chunk_id
        WHERE paper_chunks_fts MATCH ?
          AND fts.identity_key = ?
        ORDER BY bm25_score ASC
        LIMIT ?
    """
    rows = conn.execute(sql, (query, identity_key, max(4, int(top_k)))).fetchall()
    results = [dict(row) for row in rows]
    if results:
        return results
    fallback_rows = conn.execute(
        """
        SELECT chunk_id, identity_key, section_title, chunk_text, page_start, page_end,
               COALESCE(chunk_index, 0) AS chunk_index,
               COALESCE(chunk_type, 'body') AS chunk_type,
               COALESCE(page_mapping_confidence, 0) AS page_mapping_confidence,
               COALESCE(token_count, 0) AS token_count
        FROM paper_chunks
        WHERE identity_key = ?
        ORDER BY page_mapping_confidence DESC, chunk_index ASC
        LIMIT ?
        """,
        (identity_key, max(4, int(top_k))),
    ).fetchall()
    return [dict(row) for row in fallback_rows]


def answer_single_paper_question(
    conn,
    *,
    paper: dict[str, Any],
    question: str,
    model_config: dict[str, Any],
    call_llm: Callable[..., dict[str, Any]],
    top_k: int = 8,
) -> dict[str, Any]:
    identity_key = str(paper.get("identity_key") or "").strip()
    if not identity_key:
        raise QaServiceError("缺少文献标识")
    chunks = select_single_paper_chunks(conn, identity_key=identity_key, question=question, top_k=top_k)
    if not chunks:
        return {
            "answer": "现有全文证据不足，无法回答该问题。",
            "citations": [],
            "insufficient_evidence": True,
            "token_usage": {},
            "evidence_chunks": [],
        }

    prompt = prompt_builder.build_user_prompt(question, paper, chunks)
    llm_result = call_llm(
        prompt=prompt,
        model=str(model_config.get("model") or "").strip(),
        provider=str(model_config.get("llm_provider") or "ollama").strip(),
        base_url=str(model_config.get("llm_base_url") or model_config.get("ollama_base_url") or "").strip(),
        api_key=str(model_config.get("llm_api_key") or "").strip(),
        temperature=float(model_config.get("temperature", 0)),
        top_p=float(model_config.get("top_p", 0.9)),
        num_predict=int(model_config.get("num_predict", 1800)),
        request_timeout_sec=int(model_config.get("request_timeout_sec", 900)),
        system_prompt=prompt_builder.build_system_prompt(),
    )
    payload = _parse_json_payload(llm_result.get("content", ""))
    allowed_chunks = {chunk["chunk_id"]: chunk for chunk in chunks}
    normalized = citation_validator.validate_qa_response(payload, allowed_chunks)

    enriched_citations = []
    for item in normalized["citations"]:
        chunk = allowed_chunks[item["chunk_id"]]
        enriched_citations.append({
            "citation_order": item["citation_order"],
            "chunk_id": item["chunk_id"],
            "claim": item["claim"],
            "identity_key": chunk.get("identity_key") or identity_key,
            "section_title": chunk.get("section_title") or "",
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "quoted_text": chunk.get("chunk_text") or "",
        })

    return {
        "answer": normalized["answer"],
        "citations": enriched_citations,
        "insufficient_evidence": normalized["insufficient_evidence"],
        "token_usage": llm_result.get("token_usage") or {},
        "evidence_chunks": chunks,
    }


def answer_scope_question(
    conn,
    *,
    question: str,
    scope_type: str,
    collection_id: str,
    scope_label: str,
    model_config: dict[str, Any],
    call_llm: Callable[..., dict[str, Any]],
    conversation: list[dict[str, Any]] | None = None,
    top_k: int = 10,
    candidate_k: int | None = None,
    embedding_model: str = "",
    embed_query: Callable[[str], list[float]] | None = None,
    rerank_candidates: Callable[[str, list[dict[str, Any]], int], tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    retrieval_question = _contextual_retrieval_question(question, conversation)
    retrieval = retriever.retrieve_evidence(
        conn,
        question=retrieval_question,
        scope_type=scope_type,
        collection_id=collection_id,
        top_k=top_k,
        candidate_k=candidate_k,
        embedding_model=embedding_model,
        embed_query=embed_query,
    )
    candidates = retrieval["evidence"]
    rerank_metadata: dict[str, Any] = {
        "applied": False,
        "candidate_count": len(candidates),
        "result_count": min(len(candidates), top_k),
        "duration_ms": 0,
    }
    if rerank_candidates is not None and candidates:
        try:
            evidence, rerank_metadata = rerank_candidates(retrieval_question, candidates, top_k)
        except Exception as exc:
            evidence = candidates[:top_k]
            rerank_metadata["error"] = str(exc)
    else:
        evidence = candidates[:top_k]
    retrieval_mode = retrieval["retrieval_mode"]
    if rerank_metadata.get("applied"):
        retrieval_mode = f"{retrieval_mode}_rerank"
    if not evidence:
        return {
            "answer": "现有文献证据不足，无法回答该问题。",
            "citations": [],
            "insufficient_evidence": True,
            "token_usage": {},
            "evidence_chunks": [],
            "retrieval_mode": retrieval_mode,
            "rerank": rerank_metadata,
            "scope_paper_count": len(retrieval["identity_keys"]),
        }

    prompt = prompt_builder.build_scope_user_prompt(
        question,
        evidence,
        scope_label=scope_label,
        conversation=conversation,
        answer_depth=str(model_config.get("answer_depth") or "detailed"),
    )
    llm_result = call_llm(
        prompt=prompt,
        model=str(model_config.get("model") or "").strip(),
        provider=str(model_config.get("provider") or "openai_compatible").strip(),
        base_url=str(model_config.get("base_url") or "").strip(),
        api_key=str(model_config.get("api_key") or "").strip(),
        temperature=float(model_config.get("temperature", 0.1)),
        top_p=0.9,
        num_predict=int(model_config.get("max_tokens", 3200)),
        request_timeout_sec=int(model_config.get("request_timeout_sec", 180)),
        system_prompt=prompt_builder.build_scope_system_prompt(),
    )
    allowed = {
        str(item.get("source_id") or item.get("chunk_id")): item
        for item in evidence
        if str(item.get("source_id") or item.get("chunk_id") or "").strip()
    }
    token_usage = llm_result.get("token_usage") or {}
    try:
        payload = _parse_json_payload(llm_result.get("content", ""))
        normalized = citation_validator.validate_qa_response(payload, allowed)
    except (QaServiceError, citation_validator.CitationValidationError) as first_error:
        recovered = _recover_partial_payload(llm_result.get("content", ""), list(allowed.keys()))
        if recovered is not None:
            try:
                normalized = citation_validator.validate_qa_response(recovered, allowed)
            except citation_validator.CitationValidationError:
                recovered = None
        evidence_fallback = None if recovered is not None else _formula_evidence_payload(question, evidence)
        if evidence_fallback is not None:
            try:
                normalized = citation_validator.validate_qa_response(evidence_fallback, allowed)
            except citation_validator.CitationValidationError:
                evidence_fallback = None
        if recovered is not None or evidence_fallback is not None:
            repair_result = None
        else:
            repair_result = call_llm(
                prompt=prompt_builder.build_json_repair_prompt(
                    llm_result.get("content", ""),
                    list(allowed.keys()),
                ),
                model=str(model_config.get("model") or "").strip(),
                provider=str(model_config.get("provider") or "openai_compatible").strip(),
                base_url=str(model_config.get("base_url") or "").strip(),
                api_key=str(model_config.get("api_key") or "").strip(),
                temperature=0,
                top_p=0.8,
                num_predict=min(3200, int(model_config.get("max_tokens", 3200))),
                request_timeout_sec=int(model_config.get("request_timeout_sec", 180)),
                system_prompt=(
                    "你是 JSON 格式修复器。只能修复用户提供内容的 JSON 语法和结构，"
                    "不得添加新事实或使用白名单以外的 source_id。只输出合法 JSON。"
                ),
            )
        if repair_result is None:
            pass
        else:
            token_usage = _merge_token_usage(token_usage, repair_result.get("token_usage") or {})
            try:
                payload = _parse_json_payload(repair_result.get("content", ""))
                normalized = citation_validator.validate_qa_response(payload, allowed)
            except (QaServiceError, citation_validator.CitationValidationError) as repair_error:
                raise QaServiceError(
                    f"模型回答格式自动修复失败：{repair_error}（首次错误：{first_error}）"
                ) from repair_error
    citations = []
    for citation in normalized["citations"]:
        item = allowed[citation["chunk_id"]]
        citations.append({
            "citation_order": citation["citation_order"],
            "chunk_id": citation["chunk_id"],
            "claim": citation["claim"],
            "identity_key": item.get("identity_key") or "",
            "source_type": item.get("source_type") or "fulltext",
            "paper_title": item.get("title") or "",
            "section_title": item.get("section_title") or "",
            "page_start": item.get("page_start"),
            "page_end": item.get("page_end"),
            "quoted_text": item.get("chunk_text") or "",
        })
    return {
        "answer": normalized["answer"],
        "citations": citations,
        "insufficient_evidence": normalized["insufficient_evidence"],
        "token_usage": token_usage,
        "evidence_chunks": evidence,
        "retrieval_mode": retrieval_mode,
        "rerank": rerank_metadata,
        "scope_paper_count": len(retrieval["identity_keys"]),
    }
