"use client";

import { AuthorSupervisionPanel } from "./AuthorSupervisionPanel";

import { ReferenceReviewPanel } from "./ReferenceReviewPanel";

import Link from "next/link";
import { EditorialControlPanel, controlModes } from "./EditorialControlPanel";
import { ProductionPolicyPanel, PolicySummary } from "./ProductionPolicyPanel";
import { CreativeInputPanel } from "./CreativeInputPanel";
import { useEffect, useRef, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { ProjectRow } from "../../shared/types";
import { loadProductionProjects, loadProductionWorkspace, resolveProductionSnapshot, startBookProduction, pauseBookProduction, resumeBookProduction, cancelBookProduction, recoverBookChapter, loadBookProgress, type Workspace, type Progress } from "./api";

const empty: Workspace = { books: [], runs: [], profiles: [], snapshots: [], budget_scopes: [] };
const storageKey = "novel-forge.author-production.v1";
export function ProductionChainPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [project, setProject] = useState("");
  const [bookId, setBookId] = useState("");
  const [workspace, setWorkspace] = useState<Workspace>(empty);
  const [profileId, setProfileId] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [runId, setRunId] = useState("");
  const [target, setTarget] = useState(1);
  const [reason, setReason] = useState("");
  const [progress, setProgress] = useState<Progress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [restored, setRestored] = useState(false);
  const lock = useRef(false);
  const pending = useRef<{body: Record<string, unknown>; key: string} | null>(null);
  const resolution = useRef<{identity: string; key: string} | null>(null);
  const book = workspace.books.find(item => item.book_id === bookId);
  const run = workspace.runs.find(item => item.book_run_id === runId);
  const snapshot = workspace.snapshots.find(item => item.snapshot_id === snapshotId);
  const profile = workspace.profiles.find(item => item.asset_version_id === profileId);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (saved) { setProject(saved.project || ""); setBookId(saved.bookId || ""); setProfileId(saved.profileId || ""); setSnapshotId(saved.snapshotId || ""); setRunId(saved.runId || ""); setTarget(saved.target || 1); setReason(saved.reason || ""); pending.current = saved.pending || null; resolution.current = saved.resolution || null; }
    } catch { setError("本地未提交输入无法读取，请重新选择作品。"); }
    setRestored(true);
    loadProductionProjects().then(setProjects).catch(e => setError(String(e)));
  }, []);
  function persist() {
    localStorage.setItem(storageKey, JSON.stringify({ project, bookId, profileId, snapshotId, runId, target, reason, pending: pending.current, resolution: resolution.current }));
  }
  useEffect(() => { if (restored) persist(); }, [restored, project, bookId, profileId, snapshotId, runId, target, reason]);
  useEffect(() => {
    if (!restored || !project) return;
    let current = true;
    loadProductionWorkspace(project, bookId).then(value => { if (current) setWorkspace(value); }).catch(e => { if (current) setError(String(e)); });
    return () => { current = false; };
  }, [restored, project, bookId]);
  useEffect(() => {
    if (!runId) { setProgress(null); return; }
    let current = true;
    const refresh = () => loadBookProgress(runId).then(value => { if (current) setProgress(value); }).catch(e => { if (current) setError(String(e)); });
    refresh(); const timer = setInterval(refresh, 5000);
    return () => { current = false; clearInterval(timer); };
  }, [runId]);
  async function refresh() { if (project) setWorkspace(await loadProductionWorkspace(project, bookId)); }
  async function act(action: () => Promise<unknown>, message: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try { await action(); await refresh(); setNotice(message); }
    catch (e) { setError(String(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  async function resolve() {
    if (!book || !profileId) return;
    const cursor = (run?.accepted_through_chapter || 0) + 1;
    const identity = JSON.stringify([project, book.book_id, book.version, profileId, cursor]);
    if (resolution.current?.identity !== identity) resolution.current = { identity, key: crypto.randomUUID() };
    persist();
    const result = await resolveProductionSnapshot(project, book, profileId, cursor, resolution.current.key);
    setSnapshotId(result.snapshot_id);
  }
  async function start() {
    if (!book || !snapshot) return;
    const body = { project_id: project, workspace_id: book.workspace_id, book_id: bookId, input_snapshot_id: snapshot.snapshot_id, input_mode: "RESOLVED_AUTHORITY_INPUT", target_chapter_count: target };
    if (pending.current && JSON.stringify(pending.current.body) !== JSON.stringify(body)) throw new Error("上次启动尚未确认。请先恢复原输入并重试原请求，确认结果后再更改生产范围。");
    if (!pending.current) pending.current = { body, key: crypto.randomUUID() };
    persist();
    const result = await startBookProduction({ ...pending.current.body, idempotency_key: pending.current.key });
    setRunId(result.book_run_id); pending.current = null; persist();
  }
  const effectiveProfile = run ? run.frozen_profile : profile?.content;
  return <FeatureShell title="作品生产" subtitle="选择作品和已批准输入，确认生产快照，再阅读、审改和继续。">
    <section className="panel">
      <h2>作品与输入</h2>
      {workspace.dispatch_control && <p role="status">模型派发：{workspace.dispatch_control.process_dispatch_suspended ? "进程总暂停" : workspace.dispatch_control.state} · {workspace.dispatch_control.reason || "以持久项目控制和任务授权为准"}。排队输入尚未完成时请查询任务状态。</p>}
      <div className="formGrid wide">
        <label>项目<select aria-label="项目" value={project} disabled={busy} onChange={e => { setProject(e.target.value); setBookId(""); setRunId(""); setSnapshotId(""); setProfileId(""); setWorkspace(empty); }}><option value="">选择项目</option>{projects.map(p => <option key={p.project_id} value={p.project_id}>{p.title || p.project_id}</option>)}</select></label>
        <label>作品<select aria-label="作品" value={bookId} disabled={busy} onChange={e => { setBookId(e.target.value); setRunId(""); setSnapshotId(""); setProfileId(""); }}><option value="">选择作品</option>{workspace.books.map(b => <option key={b.book_id} value={b.book_id}>{b.title} · {b.status}</option>)}</select></label>
        <label>已批准生产配置<select aria-label="已批准生产配置" value={profileId} onChange={e => { setProfileId(e.target.value); setSnapshotId(""); }}><option value="">选择配置</option>{workspace.profiles.map(p => <option key={p.asset_version_id} value={p.asset_version_id}>{String(p.content.name || p.content.profile_id || p.asset_version_id)}</option>)}</select></label>
        <button className="secondaryButton" disabled={busy || !book || !profileId} onClick={() => act(resolve, "生产输入已解析并冻结，请核对快照和预算。")}>解析生产快照</button>
        <label>生产快照<select aria-label="生产快照" value={snapshotId} onChange={e => setSnapshotId(e.target.value)}><option value="">选择已冻结快照</option>{workspace.snapshots.map(s => <option key={s.snapshot_id} value={s.snapshot_id}>第 {s.narrative_chapter_cursor} 章起 · {s.snapshot_hash.slice(-12)}</option>)}</select></label>
        <label>本次生产到第几章<input aria-label="生产到第几章" type="number" min={1} value={target} onChange={e => setTarget(Number(e.target.value))} /></label>
        <button className="primaryButton" disabled={busy || !snapshot || !book || target < 1} onClick={() => act(start, "生产请求已接收。进度和停点由原生任务更新。")}>确认快照并启动</button>
        <button className="secondaryButton" disabled={busy || !project} onClick={() => act(refresh, "已刷新持久状态。")}>查询最新状态</button>
      </div>
      {book && !workspace.profiles.length && <p>此作品尚无可选择的已批准生产配置。现有设计、开书输入和资格需先补齐；解析会保留具体缺项。</p>}
      {snapshot && <p>设计准入：{snapshot.design_admission_status === "AUTHOR_SUPERVISED_DESIGN" ? "作者监督试生产 · 独立文学资格未证明" : String(snapshot.design_admission_status || "历史未标记")} · 快照校验：{snapshot.snapshot_hash} · 冻结版本：{snapshot.release_sha}</p>}
    </section>
    {(!bookId || book) && <CreativeInputPanel key={`${project}:${bookId}`} project={projects.find(p => p.project_id === project)} book={book} formationId={workspace.formation_run_id} release={workspace.release_identity} onBook={setBookId} onRefresh={refresh} />}
    {book && <ProductionPolicyPanel key={`${project}:${bookId}:${profileId}`} project={project} book={book} profile={profile} characters={workspace.approved_characters} onRefresh={refresh} onSelect={id => {setProfileId(id); setSnapshotId("");}} />}
    {book && <EditorialControlPanel key={project} project={project} book={book} current={workspace.editorial_control} onRefresh={refresh} />}
    {book && <AuthorSupervisionPanel key={`supervision:${project}:${bookId}`} project={project} book={book} />}
    {book && <ReferenceReviewPanel key={`reference:${project}:${bookId}`} project={project} book={book} />}
    <section className="panel">
      <h2>进度与恢复</h2>
      <label>生产记录<select aria-label="生产记录" value={runId} onChange={e => setRunId(e.target.value)}><option value="">选择生产记录</option>{workspace.runs.map(r => <option key={r.book_run_id} value={r.book_run_id}>{r.state} · 已接纳 {r.accepted_through_chapter}/{r.target_chapter_count} · {r.book_run_id.slice(-8)}</option>)}</select></label>
      {progress && <dl><dt>当前状态</dt><dd>{progress.state}</dd><dt>停点</dt><dd>{progress.blocking_reason || progress.blocking_class || "无已报告停点"}</dd><dt>恢复条件</dt><dd>{progress.wake_condition || progress.next_expected_transition}</dd><dt>当前任务</dt><dd>{progress.active_operation_status || "未派发"}</dd></dl>}
      <label>操作原因<input aria-label="操作原因" value={reason} onChange={e => setReason(e.target.value)} placeholder="记录暂停、恢复或取消的原因" /></label>
      <div className="studioActions">
        <button disabled={busy || !run || !reason.trim()} onClick={() => act(() => pauseBookProduction(runId, reason), "暂停请求已保存。")}>暂停</button>
        <button disabled={busy || !run || !reason.trim()} onClick={() => act(() => resumeBookProduction(runId, reason), "恢复请求已保存；资格、预算和项目暂停仍由原生门禁检查。")}>恢复</button>
        <button disabled={busy || !run?.active_chapter_request_id} onClick={() => act(() => recoverBookChapter(run!.active_chapter_request_id), "已核对并恢复原章节提交；未知外部结果仍需对账。")}>恢复章节提交</button>
        <button className="dangerButton" disabled={busy || !run || !reason.trim()} onClick={() => act(() => cancelBookProduction(runId, reason), "取消请求已保存。")}>取消</button>
        <Link className="secondaryButton" href={`/editor?${new URLSearchParams({project_id: project, book_id: bookId, book_run_id: runId})}`}>阅读正文、审稿与整稿版本</Link>
      </div>
    </section>
    <section className="panel">
      <h2>{run ? "本次生产的冻结配置" : "新请求待选择的配置"}</h2>
      <p>{run ? `来源：${run.production_profile_version} · ${run.profile_hash}。恢复沿用此版本。` : "选择配置后解析快照；尚未冻结的设置不表示已用于正文。"}</p>
      {effectiveProfile && <><PolicySummary content={effectiveProfile} /><details><summary>完整冻结配置与来源</summary><pre>{JSON.stringify(effectiveProfile, null, 2)}</pre></details></>}
      {run && <p>当前后继章节审阅确认：{run.frozen_editorial_control ? `${controlModes[run.frozen_editorial_control.policy.mode] || run.frozen_editorial_control.policy.mode} · ${run.frozen_editorial_control.policy.policy_version} · ${run.frozen_editorial_control.content_hash}` : "尚未冻结；不能把当前项目选择当作已执行配置"}</p>}
      {run && <details><summary>章节实际冻结配置与版次来源</summary><p>Context、Craft、World／Actor、审读和版次只以该章节冻结的准备记录为依据。未形成章节请求时，尚无这一级配置证据。</p><pre>{JSON.stringify(run.chapter_configuration || {}, null, 2)}</pre></details>}
      {run && !run.frozen_profile && <p>此历史生产记录未解析到配置资产，不能从当前选择推断其实际配置。</p>}
      {book && <details><summary>作品策略来源</summary><pre>{JSON.stringify(book.runtime_policy, null, 2)}</pre></details>}
      <h3>项目预算范围</h3><p>范围上限不是实际用量；项目预算不自动授权每个任务。</p>
      {!workspace.budget_scopes.length ? <p>未查到持久预算范围。</p> : workspace.budget_scopes.map(b => <details key={b.budget_scope_id}><summary>{b.owner_kind} · {b.expired ? "已过期" : "有效期内"} · {b.deadline_at}</summary><pre>{JSON.stringify(b.policy, null, 2)}</pre></details>)}
    </section>
    {notice && <p role="status" className="noticeLine">{notice}</p>}
    {error && <p role="alert" className="errorLine" style={{whiteSpace:"pre-wrap"}}>{error}</p>}
  </FeatureShell>;
}
