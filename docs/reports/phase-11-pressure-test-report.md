# Phase 11 Pressure Test Report

日期：2026-07-03

## 完成内容

1. 新增默认可运行的 12 章 Novel OS 工业化压力测试：
   - `tests/integration/test_novel_os_12_chapter_industrial_pressure.py`
2. 测试覆盖：
   - 12 个 `draft_chapter`；
   - Longform stability artifacts；
   - MKAOS source -> chunk -> knowledge card -> usage binding；
   - Context Builder unified `prose` bundle；
   - MKAOS pack 注入；
   - ReviewIssue blocking；
   - LoopRun 因 blocking issue 中止；
   - Longform Recap Agent 触发并回写；
   - Release package 生成；
   - Publish gate blocked；
   - blocking ReviewIssue 阻断 release package；
   - source chunk raw text sentinel 不进入 ContextBundle、Recap、Release Package。
3. 新增 Provider hard-stop proof 测试：
   - `tests/unit/test_provider_hard_stop_proof.py`
4. 测试覆盖：
   - token limit；
   - cost limit；
   - timeout；
   - cancel；
   - failed model call evidence；
   - route fallback 存在但 hard-stop 后不 silent fallback；
   - hard-stop 后不 silent retry。

## 代码修复

| 修复 | 原因 | 证据 |
| -- | -- | -- |
| Context Builder source policy 强制 raw source false | 调用方不应能覆盖 `source_chunk_raw_text_allowed` / runtime asset 禁止项 | `src/novel_forge/modules/context_builder/service.py:build_flow_context_bundle` |
| MKAOS flow 扩展到 revision/recap/publish/feedback | Phase 4/7/10 已需要这些 flow，服务/schema 仍停留在 P0 四 flow | `src/novel_forge/modules/mkaos/service.py`, `src/novel_forge/schemas/base.py` |
| MKAOS 新 flow 默认 usage/input/output form | 新 flow 绑定必须能通过 schema-backed asset 写入 | `src/novel_forge/modules/mkaos/service.py:_default_usage_type`, `_default_input_role`, `_default_output_form` |

## 12 章验收矩阵

| 要求 | 当前证明 | 证据 |
| -- | -- | -- |
| 12 章测试可运行 | 默认 unittest 可运行，非 env-gated | `tests/integration/test_novel_os_12_chapter_industrial_pressure.py` |
| 至少 1 次 recap 触发 | `run_longform_recap(... chapter_count=12)` 返回 recap report | 同上 |
| MKAOS Pack | `build_flow_context_bundle(... flow="prose")` 写入 `mkaos_pack_id` | 同上 |
| Context Builder | `context_builder_version=context-builder-v2-mkaos` bundle 被写入 | 同上 |
| ReviewIssue | 创建 critical `canon_conflict`，recap 又写入 longform issue | 同上 |
| LoopRun | `run_loop(... chapter_review ...)` 因 blocking issue 停止 | 同上 |
| Blocking gate | Chapter 12 publish gate decision 为 `blocked` | 同上 |
| Release package | Chapter 11 release package 可生成 | 同上 |
| Release 阻断 | Chapter 12 release package 因 blocking issue 抛错 | 同上 |
| Source leakage | sentinel 不在 ContextBundle、Recap、Release Package | 同上 |

## 测试结果

| 命令 | 结果 |
| -- | -- |
| `python3 -m unittest tests.unit.test_provider_hard_stop_proof` | 2 tests OK |
| `python3 -m unittest tests.integration.test_novel_os_12_chapter_industrial_pressure` | 1 test OK，用时约 33.7s |

## 风险

| 风险 | 级别 | 说明 | 后续处理 |
| -- | -- | -- | -- |
| 12 章测试仍是确定性 fixture | P2 | 证明工业化链路，不证明文学质量或真实 provider 输出。 | P1 可加入可选真实 provider 压力测试，但必须 hard-stop。 |
| Provider fallback 当前为 fail-closed 边界 | P2 | hard-stop 后不会 silent fallback；自动 fallback 编排尚未实现。 | 后续由 Model Router / Agent Center 增加显式人工或策略确认 fallback。 |
| 旧 env-gated long-chain pressure 仍保留 | INFO | `tests/integration/test_novel_os_long_chain_pressure.py` 仍用于可选 12/50 章扩展压力。 | 保留为慢测试入口。 |
