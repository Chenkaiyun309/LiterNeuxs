#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def history_path(output_dir: str | Path, session_id: str) -> Path:
    safe_id = SAFE_ID_RE.sub("_", str(session_id or "").strip())
    if not safe_id:
        raise ValueError("问答会话标识为空")
    return Path(output_dir) / f"{safe_id}.md"


def _quote_markdown(text: str, limit: int = 1600) -> str:
    value = str(text or "").strip()
    if len(value) > limit:
        value = value[:limit].rstrip() + "..."
    return "\n".join(f"> {line}" if line else ">" for line in value.splitlines())


def render_session_markdown(detail: dict[str, Any]) -> str:
    scope = detail.get("scope") if isinstance(detail.get("scope"), dict) else {}
    scope_label = str(scope.get("scope_label") or "")
    if not scope_label:
        scope_label = "全库文献" if detail.get("scope_type") == "library" else "文献主题库"

    lines = [
        f"# {str(detail.get('title') or '未命名问答').strip()}",
        "",
        f"- 会话 ID：`{detail.get('session_id') or ''}`",
        f"- 知识范围：{scope_label}",
        f"- 创建时间：{detail.get('created_at') or ''}",
        f"- 更新时间：{detail.get('updated_at') or ''}",
        "",
        "---",
        "",
    ]
    question_number = 0
    answer_number = 0
    for message in detail.get("messages") or []:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "").strip()
        if role == "user":
            question_number += 1
            lines.extend([f"## 问题 {question_number}", "", content, ""])
            continue
        if role != "assistant":
            continue
        answer_number += 1
        lines.extend([f"## 回答 {answer_number}", "", content, ""])
        metadata = []
        if message.get("model"):
            metadata.append(f"模型：`{message['model']}`")
        if message.get("total_tokens") is not None:
            metadata.append(
                "Token："
                f"输入 {int(message.get('prompt_tokens') or 0)} / "
                f"输出 {int(message.get('completion_tokens') or 0)} / "
                f"合计 {int(message.get('total_tokens') or 0)}"
            )
        if message.get("retrieval_mode"):
            mode = str(message.get("retrieval_mode") or "")
            label = "关键词检索"
            if mode.startswith("hybrid"):
                label = "混合检索"
            if mode.endswith("_rerank"):
                label += " + 本地精排"
            metadata.append(f"检索：{label}")
        if message.get("reranker_model"):
            duration = int(message.get("rerank_duration_ms") or 0)
            candidates = int(message.get("rerank_candidates") or 0)
            device = str(message.get("rerank_device") or "")
            metadata.append(
                f"精排：`{message['reranker_model']}` / {device or 'auto'} / "
                f"{candidates} 条 / {duration} ms"
            )
        elif message.get("rerank_error"):
            metadata.append(f"精排降级：{message['rerank_error']}")
        if metadata:
            lines.extend(["；".join(metadata), ""])

        citations = message.get("citations") or []
        if citations:
            lines.extend(["### 引用", ""])
        for citation in citations:
            order = int(citation.get("citation_order") or 0)
            title = str(citation.get("paper_title") or citation.get("identity_key") or "文献来源")
            source_type = "摘要" if citation.get("source_type") == "abstract" else "全文"
            section = str(citation.get("section_title") or "").strip()
            page = ""
            if citation.get("page_start"):
                page = f"p.{citation['page_start']}"
                if citation.get("page_end") and citation.get("page_end") != citation.get("page_start"):
                    page = f"p.{citation['page_start']}-{citation['page_end']}"
            location = " · ".join(item for item in (source_type, section, page) if item)
            lines.extend([
                f"{order}. **{title}**{f'（{location}）' if location else ''}",
                "",
                _quote_markdown(citation.get("quoted_text") or ""),
                "",
            ])
        lines.extend(["---", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_session(output_dir: str | Path, detail: dict[str, Any]) -> Path:
    output_path = history_path(output_dir, str(detail.get("session_id") or ""))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".md.tmp")
    temp_path.write_text(render_session_markdown(detail), encoding="utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(output_path)
    os.chmod(output_path, 0o600)
    return output_path


def delete_session(output_dir: str | Path, session_id: str) -> bool:
    output_path = history_path(output_dir, session_id)
    if not output_path.exists():
        return False
    output_path.unlink()
    return True
