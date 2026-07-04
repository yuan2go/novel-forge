# Trigger Test Cases

Date: 2026-07-04

These tests are prompt-level trigger tests. They are designed to verify that adopted Skills are selected for the right tasks without running destructive commands or external services by default.

## Adopted Skill Trigger Tests

| skill | test id | prompt | expected behavior | verification method |
| -- | -- | -- | -- | -- |
| `pdf` | `pdf-1` | "Use the PDF skill to extract the table of contents and page-level metadata from `docs/new/some-report.pdf`." | Skill loads `pdf`; extracts/inspects PDF, avoids raw source reuse in generated drafts | Observe Skill activation; output includes pages/metadata and source path |
| `pdf` | `pdf-2` | "Analyze this scanned PDF and tell me what OCR tools would be needed before ingestion." | Skill loads `pdf`; reports OCR path and optional deps instead of guessing | Output lists OCR prerequisites and no automatic install |
| `docx` | `docx-1` | "Create a `.docx` technical方案 for Novel OS Agent Registry, with headings, tables, and an appendix." | Skill loads `docx`; produces or plans Word document with structured sections | Output references `.docx` workflow and validation |
| `docx` | `docx-2` | "Review this Word doc with tracked changes and summarize comments without accepting changes." | Skill loads `docx`; handles tracked changes and comments carefully | Output preserves change boundary |
| `xlsx` | `xlsx-1` | "Clean this xlsx test result sheet, add pass-rate formulas, and produce a formatted workbook." | Skill loads `xlsx`; uses spreadsheet formulas and validation | Output includes formula/error-check plan |
| `xlsx` | `xlsx-2` | "Convert this messy CSV into an xlsx with separate sheets for tests, risks, and owners." | Skill loads `xlsx`; produces spreadsheet deliverable | Output includes sheet plan and no DB pipeline |
| `mcp-builder` | `mcp-1` | "Design a local MCP server for Novel Forge Audit Log queries with read-only tools and eval questions." | Skill loads `mcp-builder`; outputs tool schemas, transport, evals | Output includes MCP tool names and read-only hints |
| `mcp-builder` | `mcp-2` | "Build a Python FastMCP prototype for pgvector retrieval inspection, but do not call external services." | Skill loads `mcp-builder`; uses local-only design | Output mentions no external call and test plan |
| `claude-api` | `claude-api-1` | "Design a Claude API Agent architecture for Novel OS Evaluation Center with streaming, tool use, and cost trace." | Skill loads `claude-api`; uses Claude-specific references | Output includes API surface, streaming, token/cost notes |
| `claude-api` | `claude-api-2` | "Review our Claude Code worker boundary and explain how it differs from direct Anthropic SDK calls." | Skill loads `claude-api`; compares runtime surfaces without editing code | Output cites project boundary and Claude API concepts |
| `webapp-testing` | `webapp-1` | "Use Playwright to smoke test the local Web Admin `/editor-chief` and capture console errors." | Skill loads `webapp-testing`; uses local browser automation pattern | Output uses reconnaissance-then-action and local URL |
| `webapp-testing` | `webapp-2` | "Start the local Next.js admin console and verify `/agent-registry` renders risk and status panels." | Skill loads `webapp-testing`; uses server helper only with trusted commands | Output runs `--help` before helper if used |
| `frontend-design` | `ui-1` | "Redesign the Agent Registry page so it feels like a local Novel OS operations console, not a SaaS dashboard." | Skill loads `frontend-design`; creates subject-specific design plan | Output includes palette/type/layout/signature and project constraints |
| `frontend-design` | `ui-2` | "Improve the ReviewIssue console visual hierarchy for blocking issues and revision tasks." | Skill loads `frontend-design`; focuses on clarity and priority | Output avoids generic hero/marketing layout |
| `skill-creator` | `skill-1` | "Create a custom Skill named `novel-os-quality-eval` for evaluating draft, review, publish, and feedback artifacts." | Skill loads `skill-creator`; drafts Skill, tests, acceptance criteria | Output includes SKILL.md plan and eval prompts |
| `skill-creator` | `skill-2` | "Optimize the trigger description for `rag-mcp-agent-architecture` so it fires on RAG, MCP, Context Builder, and Agent tasks." | Skill loads `skill-creator`; improves trigger and proposes tests | Output includes before/after trigger rationale |
| `doc-coauthoring` | `doc-1` | "Co-author an architecture decision record for adopting third-party Claude Skills in Novel Forge." | Skill loads `doc-coauthoring`; guides context, structure, reader test | Output uses staged doc workflow |
| `doc-coauthoring` | `doc-2` | "Draft a technical spec for Audit Log retention and export boundaries." | Skill loads `doc-coauthoring`; creates spec scaffold | Output includes audience, impact, constraints |

## Required Coverage Map

| Required coverage | Covered by |
| -- | -- |
| PDF 文档分析 | `pdf-1`, `pdf-2` |
| docx 技术方案生成 | `docx-1` |
| xlsx 数据处理 | `xlsx-1`, `xlsx-2` |
| MCP Server 设计 | `mcp-1`, `mcp-2` |
| Claude API / Agent 架构 | `claude-api-1`, `claude-api-2` |
| Web 管理页 Playwright 测试 | `webapp-1`, `webapp-2` |
| 前端 UI 设计改造 | `ui-1`, `ui-2` |
| 自定义 Skill 创建 | `skill-1`, `skill-2` |

## Non-Destructive Verification

Recommended first verification is prompt-level dry use in Claude Code, not executing helper scripts that start servers or call external APIs. For any script-backed Skill:

1. Read `SKILL.md`.
2. Run helper script `--help` if the Skill says to do so.
3. Use only local fixture files.
4. Do not install dependencies or call real providers unless the user explicitly opts in.
