# History Question Profile

Date: 2026-07-04

## Source Status

Required file searched:

```text
docs/ai/skill-adoption/history-questions.md
```

Result: file not found. The profile below is derived from repository evidence and the current task stream captured in docs and reports, especially `docs/reports/current-engineering-progress-feature-docs.md`, Novel OS reports under `docs/reports/`, and the active user requirements for Skill adoption.

## Task-Type Classification

| Task type | Evidence in project/current task stream | Suitable for Skill? | Reason |
| -- | -- | -- | -- |
| Code audit | MKAOS design-vs-implementation audit, Novel OS final matrix, production fail-closed reviews | Yes, custom | Needs project-specific file search, matrix output, risk register, and no-code-change mode |
| Document processing | User requested PDF/docx/xlsx trigger tests; project has many architecture reports | Yes, official + custom | Official document Skills cover file formats; custom project docs Skill can enforce Novel OS report structure |
| MCP | Tool Gateway and MCP HTTP JSON-RPC work exists; user requested MCP Server design test | Yes, official + custom | `mcp-builder` is directly relevant; project-specific MCP/RAG/Agent architecture Skill still needed |
| Agent | Agent Scheduler, Agent Registry, Agent Center, runtime profiles | Yes, custom | Needs Novel OS execution contract, trace/cost/gate requirements |
| RAG | Context Builder, pgvector, Qdrant, source isolation reports | Yes, custom | Generic RAG guidance is insufficient; project needs source leakage and knowledge isolation policy |
| Frontend testing | Web admin, optional Playwright smoke, route architecture tests | Yes, official | `webapp-testing` fits local UI smoke and screenshots |
| UI design | Many Web Admin consoles, user asked UI editor/control-console improvements | Yes, official + project-specific guidance | `frontend-design` helps avoid generic UI; project design rules still come from local docs |
| Java industrial systems | Mentioned as recurring historical category by user | Candidate custom | Current repo is Python/TypeScript, but user history suggests reusable external review workflow |
| Novel system | Core repository purpose | Already covered locally | Existing root Skills cover fiction production; external official Skills should not replace them |
| Quant research | Mentioned as recurring historical category by user | Candidate custom, not official Anthropic | No direct fit in official Anthropic repo; use custom later if this remains common |

## Skill Fit By Category

| Category | Best fit |
| -- | -- |
| PDF analysis | Adopt official `pdf` |
| DOCX technical方案 generation | Adopt official `docx`; candidate `doc-coauthoring` for structured drafting |
| XLSX processing | Adopt official `xlsx` |
| MCP Server design | Adopt official `mcp-builder` |
| Claude API / Agent architecture | Adopt official `claude-api` |
| Web Admin Playwright testing | Adopt official `webapp-testing` |
| Frontend UI design改造 | Adopt official `frontend-design` |
| Custom Skill creation | Adopt official `skill-creator`; also keep Codex system `skill-creator` rules |
| Novel OS quality/eval | Custom Skill needed |
| AI comment governance | Custom Skill needed |

## Conclusion

The useful adoption strategy is selective:

1. Adopt official Skills for file formats and generic tooling.
2. Preserve project-local novel production Skills as the domain source of truth.
3. Build custom Skills for Novel OS governance, Java industrial review, RAG/MCP/Agent architecture, and AI-comment governance.
