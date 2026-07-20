# 提示词文档目录

本目录用于集中管理 LiterNexus 中与大模型生成相关的提示词。提示词按使用主题拆分，便于单独调整、评审和复用。

## 文档列表

| 文件 | 主题 | 用途 |
| --- | --- | --- |
| `system-role.md` | 系统角色 | 约束模型身份、语言和格式遵守方式 |
| `literature-review-report.md` | 科研日报与综述生成 | 根据文献标题、摘要、DOI、期刊和日期生成结构化 JSON 报告 |
| `report-style-themes.md` | 报告风格主题 | 说明报告风格提示词的组织方式 |
| `report-styles/*.md` | 单个报告风格 | 每个报告风格一份独立提示词，运行时代码直接读取 |
| `json-repair.md` | JSON 修复 | 当模型输出不合法或内容不足时，要求重新生成合规 JSON |

## 变量占位说明

以下占位符由程序运行时填入：

| 占位符 | 含义 |
| --- | --- |
| `{active_style}` | 当前报告风格 |
| `{style_instruction}` | 当前报告风格对应的具体要求 |
| `{min_research_content_chars}` | `research_content` 最少中文字符数 |
| `{reference_count}` | 本次输入文献数量 |
| `{report_date}` | 报告日期 |
| `{topic}` | 用户输入或程序推断的主题参考 |
| `{papers_text}` | 已格式化的文献信息 |
| `{error_message}` | 上一次输出的错误原因 |
| `{previous_output}` | 上一次模型输出 |
| `{original_prompt}` | 原始任务和文献信息 |

## 与代码的关系

当前运行代码中的主要提示词位于：

- `code/reports/daily_report.py` 的 `build_prompt(...)`
- `code/reports/daily_report.py` 的 `repair_prompt(...)`
- `code/reports/daily_report.py` 中 OpenAI-compatible 调用的 system message

运行时代码会读取本目录中的 Markdown 提示词代码块。编辑提示词时，优先修改本目录文件，不需要把大段提示词写回 Python 代码。
