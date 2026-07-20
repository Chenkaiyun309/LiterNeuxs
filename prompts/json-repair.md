# JSON 修复提示词

## 主题

模型输出不合法、字段缺失、内容过短或语言不符合要求时，要求重新生成合规 JSON。

## 使用位置

`code/reports/daily_report.py` 的 `repair_prompt(...)`。

## 触发场景

- 输出不是合法 JSON。
- 输出包含 Markdown、解释说明或代码块。
- 缺少必填字段。
- `research_content` 过短。
- 引用编号缺失或格式错误。
- `key_findings.evidence` 与引用编号不一致。
- 输出语言不是中文。

## 提示词模板

```text
你上一个输出不符合要求。

错误类型：
{error_type}

错误原因：
{error_message}

本次修复重点：
{repair_focus}

请严格重新输出合法 JSON。
要求：
1. 只能输出 JSON 本体
2. 不要输出解释
3. 不要输出 Markdown
4. 不要输出代码块
5. 不要新增字段
6. 必须包含以下字段：
   date, report_style, topic, research_content, key_findings, scientific_questions, methods, references
7. key_findings、scientific_questions、methods 至少各 3 条
8. research_content 需要是综合总结，不少于 {min_research_content_chars} 个字符；如果上一版是“过短”，这次请明显高于阈值，不要只刚好贴线
9. research_content 必须保留多个自然段，至少写成 3 段；每段只围绕一个小主题展开，不要把背景、方法、瓶颈、趋势混写在同一段中
10. research_content 每个自然段必须带引用编号，如 [1]
11. key_findings 必须是对象数组，每项格式为 {"conclusion": "...[1, p.4, Results]", "evidence": [{"ref_id": 1, "abstract_snippet": "", "evidence_snippet": "从该文献摘要或全文片段原文复制的连续短片段", "section": "Results", "page": "4"}]}。
12. 每条 key_findings 通常只保留 1 条最可靠 evidence；只有在两条都非常确定且能逐字回溯时才给 2 条。宁可少给，也不要凑数。
13. key_findings 每条 conclusion 都必须带引用编号，且至少一个引用编号要出现在该条 evidence.ref_id 中。
14. evidence_snippet 或 abstract_snippet 必须是对应文献摘要或全文片段中可以原文找到的连续片段，不要翻译、改写、概括、拼接或泛化。
15. 若某条 finding 找不到可靠 evidence，就删除该条 finding，重写为别的可被证据支持的 finding；不要保留无证据或弱证据 finding。
16. scientific_questions、methods 每一条都必须带引用编号，如 [1]
17. 如果上一版的 research_content 过短，这一版必须明显扩写，优先补充研究背景、总体进展、方法比较、关键瓶颈和未来趋势。
18. 允许在不引入外部事实的前提下进行高层次综述性展开，使内容更完整、更连贯，但不得虚构实验条件、结果数值和机理细节。
19. 请把 research_content 写成更完整的学术综述段落，而不是摘要拼接或简单改写。
20. 如果上一版的问题是段落组织不合格，这一版必须明确拆成多个自然段，并确保一个段落对应一个小主题。
21. 除文献原始题名、作者、期刊、DOI、abstract_snippet 和 evidence_snippet 外，topic、research_content、key_findings.conclusion、scientific_questions、methods 都必须使用中文；如果上一版主要是英文，这一版必须彻底改写为中文。
22. 如果证据来自全文 chunk，引用可以使用 [1, p.4, Results] 或 [1, Methods]；如果证据来自摘要，使用 [1] 即可。不要为没有全文 chunk 的文献编造页码或章节。
23. 当错误类型与 evidence 有关时，请优先只修复 key_findings，尽量保持 topic、research_content、scientific_questions、methods 的主旨稳定。
24. 当错误类型是 research_content_too_short 时，请优先扩写 research_content，尽量不要重写已经合格的 key_findings、scientific_questions、methods。
25. 下面给出可直接复制的证据候选。若你需要重写 key_findings，请优先从这些候选中逐字复制 evidence_snippet / abstract_snippet，不要自己改写：
{evidence_candidate_text}

你上一次的输出如下：
{previous_output}

原始任务和文献信息如下，请基于这些文献信息重新生成，不要依赖外部知识：
{original_prompt}
```

## 输出要求

- 只能输出 JSON。
- 不允许新增 schema 外字段。
- 修复时仍必须基于原始文献信息，不能补充外部事实。
