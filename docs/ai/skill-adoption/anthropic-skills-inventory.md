# Anthropic Skills Inventory

Date: 2026-07-04

## Sources

| Source | Result |
| -- | -- |
| `https://www.skills.sh/anthropics/skills` | Public skills catalog entry for `anthropics/skills` |
| `https://github.com/anthropics/skills` | Cloned to `/tmp/anthropic-skills-audit` for static review |
| Git commit | `9d2f1ae187231d8199c64b5b762e1bdf2244733d` |
| Marketplace metadata | `.claude-plugin/marketplace.json` defines `document-skills`, `example-skills`, and `claude-api` plugins |

## Repository-Level Notes

- The repository README states many skills are Apache-2.0, while `docx`, `pdf`, `pptx`, and `xlsx` are source-available document skills, not open source.
- Official Claude Code plugin commands exist in README:
  - `/plugin marketplace add anthropics/skills`
  - `/plugin install document-skills@anthropic-agent-skills`
  - `/plugin install example-skills@anthropic-agent-skills`
- This execution environment is not an interactive Claude Code session, so slash-command plugin installation was not available. Vendor fallback was used only for adopted Skills.

## Inventory

| Skill | Description summary | Dependencies / resources | Scripts | License signal | Risk points |
| -- | -- | -- | -- | -- | -- |
| `algorithmic-art` | p5.js seeded generative art | JS templates | `templates/generator_template.js`, `viewer.html` | Apache-style `LICENSE.txt` | Not project-critical; creative output only |
| `brand-guidelines` | Anthropic brand colors/typography | Static instructions | none | Apache-style `LICENSE.txt` | Anthropic brand does not match Novel Forge |
| `canvas-design` | Static visual art in PNG/PDF | Bundled fonts and font licenses | none at top level | Apache-style plus many font OFL notices | Large font payload; not needed for core engineering |
| `claude-api` | Claude API/SDK, model, streaming, tool use, MCP, agents | Large reference library by language and shared topics | none | `LICENSE.txt` complete terms | References live docs and credentials patterns; must avoid real API calls unless opt-in |
| `doc-coauthoring` | Structured documentation co-authoring workflow | Instructions only | none | No per-skill license file seen | Mentions integrations/connectors; use local files unless explicitly available |
| `docx` | Create/read/edit Word documents | OOXML schemas, office helper scripts | `accept_changes.py`, `comment.py`, office pack/unpack/validate/soffice helpers | Source-available, proprietary terms | May require LibreOffice, pandoc, global `docx`; source-available terms |
| `frontend-design` | Distinctive visual design guidance | Instructions only | none | Apache-style `LICENSE.txt` | Subjective design guidance; must still follow project UI rules |
| `internal-comms` | Internal company comms templates | Examples | none | Apache-style `LICENSE.txt` | Company-comms focused, weak project match |
| `mcp-builder` | MCP server design/build/evaluation guide | Python/TypeScript references and eval guide | `connections.py`, `evaluation.py`, `requirements.txt` | Apache-style `LICENSE.txt` | Can connect to MCP URLs and asks to fetch external SDK docs; require opt-in |
| `pdf` | PDF extract/edit/merge/forms/OCR | Forms/reference docs | PDF form/image helper scripts | Source-available, proprietary terms | Optional OCR/image deps; source-available terms; encrypted PDF commands need care |
| `pptx` | Presentation read/create/edit | OOXML helpers and pptx guides | add/clean/thumbnail plus office helpers | Source-available, proprietary terms | Useful but not required by current project; large schema payload |
| `skill-creator` | Create, test, benchmark, optimize Skills | Agents, refs, eval viewer | scripts call `claude -p`, package, validate, report | Apache-style `LICENSE.txt` | Subprocess calls to Claude CLI, eval viewer uses external fonts/CDN; use controlled mode |
| `slack-gif-creator` | Slack GIF creation | PIL/imageio/numpy requirements | GIF builder core | Apache-style `LICENSE.txt` | Irrelevant; extra media deps |
| `theme-factory` | Apply/generate themes for artifacts | Theme docs and showcase PDF | none | Apache-style `LICENSE.txt` | Nice-to-have only; possible style drift from project UI |
| `web-artifacts-builder` | Claude.ai HTML artifact builder with React/Tailwind/shadcn | Shell scripts, shadcn component tarball | `init-artifact.sh`, `bundle-artifact.sh` | Apache-style `LICENSE.txt` | Installs global pnpm and many npm deps; includes `rm -rf dist bundle.html`; manual review |
| `webapp-testing` | Local web app Playwright testing | Examples and lifecycle helper | `with_server.py` | Apache-style `LICENSE.txt` | `with_server.py` uses `shell=True`; run only trusted local commands |
| `xlsx` | Spreadsheet create/read/edit/clean/recalculate | OOXML helpers, recalc script | `recalc.py`, office helpers | Source-available, proprietary terms | Requires LibreOffice/openpyxl; macro writes to LibreOffice user config |

## Adopted Static-Review Summary

No adopted Skill contained unknown binaries. Adopted scripts are plain text Python/Markdown plus OOXML schemas. Risk is operational rather than hidden-binary: optional external tools, possible network references, shell command execution helpers, and proprietary source-available terms for document Skills.
