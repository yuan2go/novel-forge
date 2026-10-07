"use client";

import { useEffect, useRef, useState } from "react";
import { FileSearch } from "lucide-react";
import { fetchJson } from "../../shared/api";
import { PanelHeader } from "../../shared/ui";
import type { DraftEditorState } from "./api";

type Finding = {lineage_id: string; finding_digest: string; status: string; disposition?: {decision?: string};
  members: Array<{dimension: string; judgment: string; severity: string; claim: string; rationale: string; evidence: Array<Record<string, unknown>>}>};
type Report = {run_id: string; source_current: boolean; implementation_current: boolean; coverage_complete: boolean; review_complete: boolean; manifest_digest: string;
  uncovered_ranges: Array<Record<string, unknown>>; findings: Finding[]; expected_version: number; paused: boolean};
type Impact = {required: unknown[]; needs_review: unknown[]; preserve: unknown[]; unknown: unknown[]; exact_dependency_closure: unknown[]; semantic_candidates: unknown[]};
type Proposal = {proposal_id: string; status: string};
export type ReviewSource = {source_review_run_id: string; source_lineage_id: string};

export function ProseReviewPanel({state, onSelect}: {state: DraftEditorState; onSelect: (source: ReviewSource) => void}) {
  const [bookRun, setBookRun] = useState(state.book_runs[0] || "");
  const [runs, setRuns] = useState<Array<{run_id: string}>>([]);
  const [runId, setRunId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState("");
  const [proposed, setProposed] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [impacts, setImpacts] = useState<Record<string, Impact>>({});
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [policy, setPolicy] = useState({policy_version: "author-prose-review.v1", window_codepoints: 4000, overlap_codepoints: 200, context_token_budget: 16000, maximum_windows: 8, execution_mode: "AUTOMATIC"});
  const planPrefix = `/product/production/book-authority/books/${encodeURIComponent(state.book_id)}/plan-changes`;
  const proposalKey = `novel-forge:review-plan:${state.project_id}:${runId}`;
  const pending = useRef<{path: string; body: Record<string, unknown>} | null>(null);
  const prefix = `/product/production/book-authority/runs/${encodeURIComponent(bookRun)}/prose-reviews`;
  const query = new URLSearchParams({project_id: state.project_id, workspace_id: state.workspace_id});
  function showError(error: unknown) {setMessage(error instanceof Error ? error.message : String(error));}
  useEffect(() => {
    if (!bookRun) {setReport(null); setRuns([]); return;}
    let active = true;
    fetchJson<Array<{run_id: string}>>(`${prefix}?${query}`).then((rows) => {if (active) {setRuns(rows); setRunId(rows[0]?.run_id || "");}}).catch(showError);
    return () => {active = false;};
  }, [bookRun, state.project_id]);
  useEffect(() => {
    if (!runId) {setReport(null); return;}
    let active = true;
    setImpacts({}); setProposal(null);
    const savedProposal = localStorage.getItem(proposalKey);
    if (savedProposal) fetchJson<Proposal>(`${planPrefix}/${encodeURIComponent(savedProposal)}?project_id=${encodeURIComponent(state.project_id)}`).then((next) => {if (active) setProposal(next);}).catch(showError);
    fetchJson<Report>(`${prefix}/${encodeURIComponent(runId)}?${query}`).then((row) => {if (active) setReport(row);}).catch(showError);
    return () => {active = false;};
  }, [runId, bookRun]);
  async function refresh() {if (runId) setReport(await fetchJson<Report>(`${prefix}/${encodeURIComponent(runId)}?${query}`));}
  async function submit(path: string, body: Record<string, unknown>) {
    if (busy) return;
    setBusy(true); setMessage("");
    pending.current ||= {path, body: {...body, project_id: state.project_id, workspace_id: state.workspace_id,
      idempotency_key: crypto.randomUUID(), trace_id: `trace:${crypto.randomUUID()}`, correlation_id: `correlation:${crypto.randomUUID()}`}};
    try {
      const result = await fetchJson<{run_id?: string; proposal?: Proposal; semantic_impact?: Impact}>(pending.current.path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(pending.current.body)});
      if (result.proposal) {setProposal(result.proposal); localStorage.setItem(proposalKey, result.proposal.proposal_id);}
      pending.current = null;
      if (result.run_id) {
        setRuns(await fetchJson<Array<{run_id: string}>>(`${prefix}?${query}`)); setRunId(result.run_id);
        setReport(await fetchJson<Report>(`${prefix}/${encodeURIComponent(result.run_id)}?${query}`));
      } else await refresh();
      setMessage("处理决定已登记；未直接改变已接纳正文或批准未来计划。");
    } catch (error) {
      showError(error);
      const detail = error instanceof Error ? error.message : String(error);
      if (/LONGFORM_PROSE_.*(CONFLICT|INVALID|MISSING|STALE)|PERMISSION_DENIED/.test(detail)) pending.current = null;
    } finally {setBusy(false);}
  }
  function disposition(finding: Finding, decision: string) {
    void submit(`${prefix}/${runId}/findings/${encodeURIComponent(finding.lineage_id)}/disposition`, {
      expected_version: report?.expected_version, finding_digest: finding.finding_digest, decision, rationale: reason,
      consumer_asset_version_id: decision === "CURRENT_CANDIDATE_REVISION" ? state.session?.candidate_asset_version_id : ""});
  }
  async function preview(finding: Finding) {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      const result = await fetchJson<{semantic_impact: Impact}>(`${prefix}/${runId}/findings/${encodeURIComponent(finding.lineage_id)}/impact-preview`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({project_id: state.project_id, workspace_id: state.workspace_id,
          idempotency_key: crypto.randomUUID(), trace_id: `trace:${crypto.randomUUID()}`, correlation_id: `correlation:${crypto.randomUUID()}`,
          expected_version: report?.expected_version, finding_digest: finding.finding_digest, target_asset_version_id: target, proposed_asset_version_id: proposed, rationale: reason})});
      setImpacts((current) => ({...current, [finding.lineage_id]: result.semantic_impact}));
    } catch (error) {showError(error);} finally {setBusy(false);}
  }
  async function controlPlan(action: "approve" | "reject" | "activate" | "refresh") {
    if (!proposal || busy) return;
    setBusy(true); setMessage("");
    const url = `${planPrefix}/${encodeURIComponent(proposal.proposal_id)}`;
    try {
      const next = action === "refresh" ? await fetchJson<Proposal>(`${url}?project_id=${encodeURIComponent(state.project_id)}`) :
        await fetchJson<Proposal>(`${url}/${action === "activate" ? "activate" : "decisions"}`, {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({project_id: state.project_id, actor_id: "", ...(action === "activate" ? {} : {approved: action === "approve", reason})})});
      setProposal(next);
      setMessage(action === "activate" ? "已执行获批未来计划变更；历史接纳正文仍保持版本记录。" : "计划状态已更新；批准与执行是独立动作。");
    } catch (error) {showError(error);} finally {setBusy(false);}
  }
  return <section className="panel"><PanelHeader title="跨窗口正文审读与处理" icon={<FileSearch size={18} />} />
    <p>覆盖表示本次实际提供给审稿的正文范围，不代表所有质量问题均已排除。</p>
    {message ? <p role="status">{message}</p> : null}
    {!state.book_runs.length ? <p>当前 Book 尚无可查询的生产批次。</p> : <div className="studioActions">
      <label>生产批次 <select aria-label="审读生产批次" value={bookRun} onChange={(event) => {pending.current = null; setBookRun(event.target.value);}}>
        {state.book_runs.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
      <label>审读版本 <select aria-label="审读版本" value={runId} onChange={(event) => {pending.current = null; setRunId(event.target.value);}}>
        <option value="">暂无审读</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id}</option>)}</select></label>
      <button className="secondaryButton" disabled={busy || !runId} onClick={() => refresh().catch(showError)}>刷新覆盖与处理</button>
    </div>}
    {bookRun ? <details><summary>审读范围与高级容量设置</summary>
      <p>只在选择审读后运行。资源使用作品已有授权，暂停与恢复不追加付费；正文变化后重新绑定版本。</p>
      <label>审读策略版本<input aria-label="审读策略版本" value={policy.policy_version} onChange={event => setPolicy({...policy, policy_version: event.target.value})} /></label>
      {([['window_codepoints', '每窗字数'], ['overlap_codepoints', '相邻重叠字数'], ['context_token_budget', '完整请求 token 上限'], ['maximum_windows', '最多审读窗口']] as const).map(([key, label]) => <label key={key}>{label}<input type="number" min={key === 'overlap_codepoints' ? 0 : 1} aria-label={label} value={policy[key]} onChange={event => setPolicy({...policy, [key]: Number(event.target.value)})} /></label>)}
      <button className="secondaryButton" disabled={busy || !!pending.current || !policy.policy_version.trim() || policy.window_codepoints < 1 || policy.overlap_codepoints < 0 || policy.overlap_codepoints >= policy.window_codepoints || policy.context_token_budget < 1 || policy.maximum_windows < 1} onClick={() => submit(prefix, {policy})}>开始按需审读当前稿件</button>
    </details> : null}
    {pending.current ? <div className="studioActions"><button className="secondaryButton" disabled={busy} onClick={() => {const action = pending.current; if (action) void submit(action.path, action.body);}}>重试上次审读处理</button><button className="secondaryButton" disabled={busy} onClick={() => {pending.current = null; setMessage("已停止客户端重试；服务器进度按实际回执保留。"); void refresh().catch(showError);}}>放弃此次重试并刷新</button></div> : null}
    {report ? <>
      <p>正文身份：{report.source_current ? "仍与选定来源版本一致" : "版本已漂移，旧结果不可用于新决定"} · 实现身份：{report.implementation_current ? "与冻结版本一致" : "实现已变化，需重新冻结"} · 正文覆盖：{report.coverage_complete ? "已覆盖冻结正文" : "仍有未覆盖范围"} · 审读任务：{report.review_complete ? "全部窗口已完成" : "仍有待审窗口或跨窗比较"} · {report.paused ? "已暂停" : "可继续"}</p>
      <p style={{overflowWrap: "anywhere"}}>冻结整稿：{report.manifest_digest}</p>
      {report.uncovered_ranges.map((range, index) => <p key={index}>未覆盖：{JSON.stringify(range)}</p>)}
      <label>处理理由<textarea aria-label="审读处理理由" value={reason} onChange={(event) => setReason(event.target.value)} rows={2} /></label>
      <div className="studioActions">
        <button className="primaryButton" disabled={busy || !!pending.current || !report.source_current || !report.implementation_current || report.paused || report.review_complete} onClick={() => submit(`${prefix}/${runId}/advance`, {expected_version: report.expected_version})}>推进一个审读窗口</button>
        <button className="secondaryButton" disabled={busy || !!pending.current || !report.source_current || !report.implementation_current || !reason.trim()} onClick={() => submit(`${prefix}/${runId}/control`, {expected_version: report.expected_version, paused: !report.paused, reason})}>{report.paused ? "恢复审读（原额度）" : "暂停审读"}</button>
      </div>
      {report.findings.map((finding) => <article key={finding.lineage_id} className="panel">
        <p style={{overflowWrap: "anywhere"}}>问题 {finding.lineage_id} · {finding.status} · {finding.disposition?.decision || "待处理"}</p>
        {finding.members.map((member, index) => <div key={index}><p>{member.dimension} · {member.judgment} · {member.severity}</p><p>{member.claim}</p><p>{member.rationale}</p>
          {member.evidence.map((evidence, i) => <pre key={i} style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{JSON.stringify(evidence, null, 2)}</pre>)}
        </div>)}
        <div className="studioActions">
          <button className="secondaryButton" disabled={!report.source_current || !report.implementation_current || busy || !!pending.current} onClick={() => onSelect({source_review_run_id: runId, source_lineage_id: finding.lineage_id})}>以此问题改稿</button>
          <button className="secondaryButton" disabled={!report.source_current || !report.implementation_current || busy || !!pending.current || !reason.trim() || !state.session?.candidate_asset_version_id} onClick={() => disposition(finding, "CURRENT_CANDIDATE_REVISION")}>关联已保存的修改候选</button>
          <button className="secondaryButton" disabled={!report.source_current || !report.implementation_current || busy || !!pending.current || !reason.trim()} onClick={() => disposition(finding, "KEEP_HISTORY")}>保留历史正文</button>
        </div>
        <details><summary>提出未来计划变更</summary>
          <input aria-label={`原计划版本 ${finding.lineage_id}`} value={target} onChange={(event) => setTarget(event.target.value)} placeholder="精确原计划 asset version" />
          <input aria-label={`候选计划版本 ${finding.lineage_id}`} value={proposed} onChange={(event) => setProposed(event.target.value)} placeholder="已生成的候选计划 asset version" />
          <button className="secondaryButton" disabled={!report.source_current || !report.implementation_current || busy || !!pending.current || !target || !proposed || !reason.trim()} onClick={() => preview(finding)}>查看影响</button>
          {impacts[finding.lineage_id] ? <div><p>语义推测需授权确认，不自动建立硬依赖或批准重写。</p>{([['required', '必改（批准后）'], ['needs_review', '待审'], ['preserve', '保留'], ['unknown', '未知'], ['exact_dependency_closure', '精确依赖闭包'], ['semantic_candidates', '语义候选与位置证据']] as const).map(([key, title]) => <details key={key}><summary>{title} · {impacts[finding.lineage_id][key].length}</summary><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{JSON.stringify(impacts[finding.lineage_id][key], null, 2)}</pre></details>)}</div> : null}
          <button className="secondaryButton" disabled={!report.source_current || !report.implementation_current || busy || !!pending.current || !target || !proposed || !reason.trim()} onClick={() => submit(`${prefix}/${runId}/findings/${encodeURIComponent(finding.lineage_id)}/plan-change`, {
            expected_version: report.expected_version, finding_digest: finding.finding_digest,
            target_asset_version_id: target, proposed_asset_version_id: proposed, rationale: reason})}>登记 Plan Change 提案</button>
        </details>
      </article>)}
      {proposal ? <div className="panel"><h3>未来计划授权与执行</h3><p style={{overflowWrap: "anywhere"}}>{proposal.proposal_id} · {proposal.status}</p>
        <button className="secondaryButton" disabled={busy} onClick={() => controlPlan("refresh")}>刷新计划状态</button>
        <button className="secondaryButton" disabled={busy || proposal.status !== "PENDING_APPROVAL" || !reason.trim()} onClick={() => controlPlan("approve")}>批准未来计划</button>
        <button className="secondaryButton" disabled={busy || proposal.status !== "PENDING_APPROVAL" || !reason.trim()} onClick={() => controlPlan("reject")}>拒绝未来计划</button>
        <button className="primaryButton" disabled={busy || !["APPROVED", "ACTIVATION_PENDING"].includes(proposal.status)} onClick={() => controlPlan("activate")}>执行已批准计划</button>
      </div> : null}
    </> : null}
  </section>;
}
