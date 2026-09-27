"use client";

import { FileSearch, GitPullRequest, Save } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { ProjectRow } from "../../shared/types";
import { PanelHeader } from "../../shared/ui";
import { loadEditorProjects, loadEditorDrafts, loadDraftEditor, submitEditorCommand, requestAuthorReview, loadAuthorReview, type AuthorReviewStatus,
  type EditorDraft, type DraftEditorState, type EditorCommand } from "./api";
import { ProseReviewPanel, type ReviewSource } from "./ProseReviewPanel";
import { exactOffset, retainExactLineEndings } from "./text";
import { EditionPanel } from "./EditionPanel";

const EDITOR_COMMANDS = ["保存候选", "采用候选", "拒绝候选", "提交章节复核"];
const storageKey = (draft: EditorDraft) => `novel-forge:author-input:${draft.project_id}:${draft.asset_version_id}`;
const workingText = (state: DraftEditorState) => state.session?.status !== "REJECTED"
  ? state.candidates.find((item) => item.asset_version_id === state.session?.candidate_asset_version_id)?.content.text ?? state.text : state.text;

export function EditorPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [preferredBookRun, setPreferredBookRun] = useState("");
  const [drafts, setDrafts] = useState<EditorDraft[]>([]);
  const [draftId, setDraftId] = useState("");
  const [state, setState] = useState<DraftEditorState | null>(null);
  const [editorText, setEditorText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [rationale, setRationale] = useState("");
  const [rights, setRights] = useState<"ORIGINAL_AUTHOR_INPUT" | "AUTHORIZED_INPUT">("ORIGINAL_AUTHOR_INPUT");
  const [selection, setSelection] = useState<{start: number; end: number} | null>(null);
  const [reviewSource, setReviewSource] = useState<ReviewSource | null>(null);
  const [pending, setPending] = useState<EditorCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewStatus, setReviewStatus] = useState<AuthorReviewStatus | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const lock = useRef(false);
  const editor = useRef<HTMLTextAreaElement>(null);
  const reviewKey = useRef("");
  const draft = drafts.find((item) => item.asset_version_id === draftId);
  const dirty = state !== null && editorText !== savedText;
  const candidate = state?.candidates.find((item) => item.asset_version_id === state.session?.candidate_asset_version_id);
  const canLeave = () => !(dirty || pending) || window.confirm("当前有未保存输入或待确认请求。保留本地输入并切换？");

  useEffect(() => { setPreferredBookRun(new URLSearchParams(window.location.search).get("book_run_id") || ""); loadEditorProjects().then((rows) => {setProjects(rows); const requested = new URLSearchParams(window.location.search).get("project_id"); setProjectId(requested ? rows.find(row => row.project_id === requested)?.project_id || "" : rows[0]?.project_id || "");}).catch(showError); }, []);
  useEffect(() => {
    if (!projectId) return;
    let active = true;
    loadEditorDrafts(projectId).then((rows) => { if (active) {const params = new URLSearchParams(window.location.search); const requested = params.get("project_id") === projectId ? params.get("book_id") : null; const scoped = requested ? rows.filter(item => item.book_id === requested) : rows; setDrafts(scoped); setDraftId(scoped.find((item) => item.book_id)?.asset_version_id || "");} }).catch(showError);
    return () => {active = false;};
  }, [projectId]);
  useEffect(() => {
    if (!draft) {setState(null); return;}
    let active = true;
    setState(null); setReviewStatus(null); setError(""); setSelection(null); setReviewSource(null); reviewKey.current = "";
    loadDraftEditor(draft).then((next) => {
      if (!active) return;
      setState(next);
      const previousReview = localStorage.getItem(`novel-forge:author-review-run:${next.project_id}:${next.session?.decision_asset_version_id}`);
      if (previousReview) loadAuthorReview(next.project_id, previousReview).then((run) => {if (active) setReviewStatus(run);}).catch(showError);
      const stored = localStorage.getItem(storageKey(draft));
      const recovered = stored ? JSON.parse(stored) : null;
      const saved = workingText(next);
      setSavedText(saved);
      setEditorText(recovered?.base_text_hash === next.base_text_hash ? recovered.text : saved);
      setPending(recovered?.pending || null);
      if (recovered?.text && recovered.text !== next.text) setNotice("已恢复本机尚未提交的作者输入；它尚未改变已接纳正文。");
    }).catch(showError);
    return () => {active = false;};
  }, [draftId, drafts]);
  useEffect(() => {
    if (!state || !draft || state.base_asset_version_id !== draft.asset_version_id || state.project_id !== draft.project_id) return;
    if (dirty || pending) localStorage.setItem(storageKey(draft), JSON.stringify({text: editorText, base_text_hash: state.base_text_hash, pending}));
    else localStorage.removeItem(storageKey(draft));
  }, [editorText, state, draft, dirty, pending]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {if (dirty || pending) {event.preventDefault(); event.returnValue = "";}};
    const navigate = (event: MouseEvent) => {
      if (!(dirty || pending) || !(event.target instanceof Element) || !event.target.closest("a[href]")) return;
      if (!window.confirm("有未保存的作者输入。保留本地输入并离开？")) {event.preventDefault(); event.stopPropagation();}
    };
    window.addEventListener("beforeunload", guard);
    document.addEventListener("click", navigate, true);
    return () => {window.removeEventListener("beforeunload", guard); document.removeEventListener("click", navigate, true);};
  }, [dirty, pending]);

  function showError(caught: unknown) { setError(caught instanceof Error ? caught.message : String(caught)); }
  async function reload(preserve = true) {
    if (!draft) return;
    try {
      const next = await loadDraftEditor(draft); setState(next); setSavedText(workingText(next));
      if (!preserve) {setEditorText(workingText(next)); setSelection(null);}
      setNotice(preserve ? "已重新加载当前版本，作者输入已保留。请核对差异后重试。" : "已撤销未提交修改。");
    } catch (caught) {showError(caught);}
  }
  function baseCommand(action: EditorCommand["action"]): EditorCommand {
    if (!state) throw new Error("请先读取精确版本");
    return {action, project_id: state.project_id, workspace_id: state.workspace_id, book_id: state.book_id,
      chapter: state.chapter, base_asset_version_id: state.base_asset_version_id, base_asset_hash: state.base_asset_hash,
      base_text_hash: state.base_text_hash, expected_version: state.version, idempotency_key: crypto.randomUUID()};
  }
  async function send(command: EditorCommand) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setPending(command);
    try {
      const result = await submitEditorCommand(command);
      setPending(null); reviewKey.current = ""; setReviewStatus(null);
      if (draft) {
        const next = await loadDraftEditor(draft); setState(next); setSavedText(workingText(next));
        setEditorText(workingText(next));
      }
      setNotice(result.editor_status === "ADOPTED_PENDING_REVIEW" ? "已采用候选，等待章节复核。尚未接纳章节或完成整书。" :
        result.editor_status === "REJECTED" ? "已拒绝候选，原正文未改变。" : "作者实际输入已保存为独立候选。请检查修改对照后采用或拒绝。");
    } catch (caught) {
      showError(caught);
      const message = caught instanceof Error ? caught.message : String(caught);
      if (/AUTHOR_VERSION_CONFLICT|AUTHOR_BASE_STALE|AUTHOR_BASE_HASH_CONFLICT|AUTHOR_EDIT_|AUTHOR_SCENE_|AUTHOR_NO_CHANGE/.test(message)) setPending(null);
    } finally {lock.current = false; setBusy(false);}
  }
  function save() {
    const command = {...baseCommand("save"), text: editorText, rights_basis: rights,
      ...(selection ? {allowed_ranges: [selection]} : {}), ...(reviewSource || {})};
    void send(command);
  }
  function decide(action: "accept" | "reject") {
    void send({...baseCommand(action), candidate_asset_version_id: candidate?.asset_version_id, rationale});
  }
  async function review() {
    if (!state || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    const key = `novel-forge:author-review:${state.project_id}:${state.session?.decision_asset_version_id}`;
    reviewKey.current ||= localStorage.getItem(key) || crypto.randomUUID();
    localStorage.setItem(key, reviewKey.current);
    try {
      const result = await requestAuthorReview(state, reviewKey.current);
      localStorage.setItem(`novel-forge:author-review-run:${state.project_id}:${state.session?.decision_asset_version_id}`, result.root_operation_id);
      setReviewStatus(await loadAuthorReview(state.project_id, result.root_operation_id));
      setNotice(`章节复核已登记：${result.root_operation_id}。后续 Review、Canon 与 Book 接纳分别受原生门控。`);
    } catch (caught) {showError(caught);} finally {lock.current = false; setBusy(false);}
  }

  return <FeatureShell title="作者编辑器" subtitle="读取精确版本，保存真实作者输入，检查对照并采用候选，再进入章节复核。">
    {notice ? <div role="status" className="noticeLine">{notice}</div> : null}
    {error ? <div role="alert" className="errorLine">{error}<button className="secondaryButton" disabled={busy} onClick={() => reload()}>重新加载并保留输入</button></div> : null}
    <section className="panel"><div className="studioActions">
      <label>项目 <select aria-label="项目" value={projectId} disabled={busy} onChange={(event) => {if (canLeave()) setProjectId(event.target.value);}}>
        {projects.map((item) => <option value={item.project_id} key={item.project_id}>{item.title}</option>)}</select></label>
      <label>稿件版本 <select aria-label="稿件版本" value={draftId} disabled={busy} onChange={(event) => {if (canLeave()) setDraftId(event.target.value);}}>
        <option value="">选择已绑定 Book 的稿件</option>{drafts.map((item) => <option disabled={!item.book_id} key={item.asset_version_id} value={item.asset_version_id}>{item.title} · {item.asset_type} · {item.asset_version_id.slice(-8)}</option>)}</select></label>
      <span>{dirty ? "有未保存修改" : "无未保存修改"}</span>
    </div></section>
    <section className="editorWorkbenchGrid">
      <aside className="panel"><PanelHeader title="相关资料侧栏" icon={<FileSearch size={18} />} />
        <p>项目：{state?.project_id || "—"}</p><p>工作区：{state?.workspace_id || "—"}</p><p>Book：{state?.book_id || "—"}</p>
        <p>章节：{state?.chapter || "—"}</p><p style={{overflowWrap: "anywhere"}}>基准版本：{state?.base_asset_version_id || "—"}</p>
        <p style={{overflowWrap: "anywhere"}}>正文 hash：{state?.base_text_hash || "—"}</p><p>编辑版本：{state?.version ?? "—"}</p>
        <p>保存草稿、采用候选、接纳章节、完成整书是四个独立动作。</p>
        <h3>基准诊断</h3>
        {state?.diagnostics.length ? state.diagnostics.map((report) => <div key={report.asset_version_id}>
          <p className="pathText">{report.asset_version_id}</p>{report.content.issues?.map((issue) => <p key={issue.code}>{issue.severity} · {issue.message}</p>)}
        </div>) : <p>此精确版本尚无诊断记录。</p>}
      </aside>
      <div className="panel richEditorPanel"><PanelHeader title="富文本编辑区" icon={<Save size={18} />} />
        <textarea ref={editor} aria-label="章节正文" className="richDraftEditor" value={editorText} disabled={!state || busy || !!pending} onChange={(event) => setEditorText((current) => retainExactLineEndings(current, event.target.value))} rows={20} />
        <p>{Array.from(editorText).length} 字符 · {selection ? `限定基准选区 [${selection.start}, ${selection.end})` : "全章作者编辑"}</p>
        {reviewSource ? <p style={{overflowWrap: "anywhere"}}>针对审读问题：{reviewSource.source_lineage_id}<button className="secondaryButton" onClick={() => setReviewSource(null)}>取消问题关联</button></p> : null}
        <div className="studioActions">
          <button className="secondaryButton" disabled={dirty || !state || editorText !== state.text || busy || !!pending} onClick={() => {
            const area = editor.current; if (!area || area.selectionStart === area.selectionEnd) return;
            setSelection({start: Array.from(editorText.slice(0, exactOffset(editorText, area.selectionStart))).length, end: Array.from(editorText.slice(0, exactOffset(editorText, area.selectionEnd))).length});
          }}>锁定当前选区</button>
          <button className="secondaryButton" disabled={busy || !!pending} onClick={() => setSelection(null)}>取消选区限制</button>
          <button className="secondaryButton" disabled={!dirty || busy || !!pending} onClick={() => reload(false)}>撤销未提交修改</button>
        </div>
        <label>输入权利 <select aria-label="输入权利" value={rights} onChange={(event) => setRights(event.target.value as typeof rights)}>
          <option value="ORIGINAL_AUTHOR_INPUT">本人原创输入</option><option value="AUTHORIZED_INPUT">已获授权的输入</option></select></label>
        <button className="primaryButton" disabled={!dirty || busy || !!pending} onClick={save}>{EDITOR_COMMANDS[0]}</button>
        {pending ? <button className="primaryButton" disabled={busy} onClick={() => send(pending)}>重试上次请求（相同幂等键）</button> : null}
      </div>
      <aside className="panel"><PanelHeader title="版本历史侧栏" icon={<GitPullRequest size={18} />} />
        <p>当前候选状态：{state?.session?.status || "尚无候选"}</p>
        {state?.candidates.map((item) => <p key={item.asset_version_id} style={{overflowWrap: "anywhere"}}>候选 {item.asset_version_id} · {item.content.text_hash}</p>)}
        {state?.decisions.map((item) => <p key={item.asset_version_id}>{String(item.content.decision)} · {String(item.content.rationale)}</p>)}
      </aside>
    </section>
    <section className="workspaceGrid">
      <div className="panel"><PanelHeader title="修改前" icon={<FileSearch size={18} />} /><pre style={{whiteSpace: "pre-wrap"}}>{state?.text}</pre></div>
      <div className="panel"><PanelHeader title="修改后候选" icon={<FileSearch size={18} />} /><pre style={{whiteSpace: "pre-wrap"}}>{candidate?.content.text || editorText}</pre></div>
    </section>
    <section className="panel"><PanelHeader title="修改对照与决定" icon={<GitPullRequest size={18} />} />
      {candidate?.content.edits.map((edit, index) => <div key={index}><p>基准位置 [{edit.start}, {edit.end})</p><del>{edit.before || "（插入位置）"}</del><ins>{edit.after || "（删除）"}</ins></div>)}
      <p>诊断与语义影响：新候选尚需独立复核。作者采用不代表连续性、Craft 或正文质量已通过。</p>
      <textarea aria-label="决定理由" value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="说明采用或拒绝本候选的理由" rows={3} />
      <div className="studioActions">
        <button className="primaryButton" disabled={busy || !!pending || dirty || state?.session?.status !== "SAVED_CANDIDATE" || !rationale.trim()} onClick={() => decide("accept")}>{EDITOR_COMMANDS[1]}</button>
        <button className="secondaryButton" disabled={busy || !!pending || state?.session?.status !== "SAVED_CANDIDATE" || !rationale.trim()} onClick={() => decide("reject")}>{EDITOR_COMMANDS[2]}</button>
        <button className="primaryButton" disabled={busy || !!pending || dirty || !!reviewStatus || (!!state?.book_request && (!state.book_request.is_current || !state.book_request.unaccepted)) || state?.session?.status !== "ADOPTED_PENDING_REVIEW"} onClick={review}>{EDITOR_COMMANDS[3]}</button>
      </div>
    </section>
    <section className="panel">
      <p>提交章节复核会登记模型工作，沿用项目现有的 Provider 资格、授权与预算门控。</p>
      {reviewStatus ? <>
        <h3>章节复核进度</h3><p style={{overflowWrap: "anywhere"}}>{reviewStatus.root_operation_id} · {reviewStatus.run.status}</p>
        <button className="secondaryButton" disabled={busy} onClick={() => state && loadAuthorReview(state.project_id, reviewStatus.root_operation_id).then(setReviewStatus).catch(showError)}>刷新章节复核状态</button>
        <p>Book 接纳：{reviewStatus.acceptance?.status || "尚未接纳"}</p>
        {reviewStatus.run.operations.map((operation) => <p key={operation.operation_id}>{operation.definition_name} · {operation.status}</p>)}
        {Object.entries(reviewStatus.artifacts).filter(([kind]) => ["diagnoses", "gates"].includes(kind)).flatMap(([kind, rows]) => rows.map((row) => <details key={row.asset_version_id}><summary>{kind} · {row.asset_type} · {row.asset_version_id}</summary><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{JSON.stringify(row.content, null, 2)}</pre></details>))}
        <a href="/manuscript">前往章节生产工作台查看后续接纳门控</a>
      </> : null}
    </section>
    {state ? <EditionPanel key={`edition:${state.project_id}:${state.book_id}`} state={state} preferredBookRun={preferredBookRun} /> : null}
    {state ? <ProseReviewPanel key={`${state.project_id}:${state.book_id}`} state={state} onSelect={(source) => {
      setReviewSource(source); setNotice("已选定审读问题；编辑正文并保存后，可显式关联修改候选。"); editor.current?.focus();
    }} /> : null}
  </FeatureShell>;
}
