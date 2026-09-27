"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, ApiError, fetchJson } from "../../shared/api";
import type { DraftEditorState } from "./api";
import { ScreenplayPanel } from "./ScreenplayPanel";

type Unit = { unit_id: string; title: string; text: string; text_hash: string; chapter_plan_asset_version_id: string; source_ranges: unknown[]; scene_artifacts: unknown[] };
type Manifest = { manifest_digest: string; units: Unit[]; impact?: { earliest_affected_position: number; required_revalidation_unit_ids: string[] } };
type Revision = { revision_id: string; base_revision_id: string | null; manifest: Manifest; edition: { version: number; current_revision_id: string } };
type EditionDiff = { changes: Array<{ unit_id: string; before_position: number | null; after_position: number | null; diff: string }> };
type EditionState = { head: { version: number; selected_revision_id: string }; source_manifest?: Manifest; revision?: Revision;
  editions: Array<{ edition_id: string; version: number; current_revision_id: string }>;
  adaptation_updates?: Array<{asset_version_id: string; source_asset_version_id: string}>;
  events?: Array<{ event_id: string; event_kind: string; content: Record<string, unknown> }>;
  validation_result?: { book_run_id: string; manifest: Manifest; diff: EditionDiff };
  diff?: EditionDiff };
type Pending = { action: string; project_id: string; workspace_id: string; book_run_id: string; data: Record<string, unknown>; idempotency_key: string };

export function EditionPanel({ state }: { state: DraftEditorState }) {
  const [runId, setRunId] = useState(state.book_runs[0] || "");
  const [revisionId, setRevisionId] = useState("");
  const [edition, setEdition] = useState<EditionState | null>(null);
  const [units, setUnits] = useState<Unit[]>([]);
  const [mapping, setMapping] = useState("");
  const [position, setPosition] = useState(0);
  const [reason, setReason] = useState("");
  const [changeKind, setChangeKind] = useState("EXPRESSION");
  const [validationRun, setValidationRun] = useState("");
  const [inputSnapshot, setInputSnapshot] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const lock = useRef(false);
  const generation = useRef(0);
  const scope = { project_id: state.project_id, workspace_id: state.workspace_id, book_run_id: runId };
  const revision = edition?.revision;
  const dirty = !!revision && JSON.stringify(units) !== JSON.stringify(revision.manifest.units);
  const unappliedMapping = (() => {
    if (!mapping.trim()) return false;
    try { return JSON.stringify(JSON.parse(mapping)) !== JSON.stringify(units); } catch { return true; }
  })();
  const unsavedInputs = dirty || unappliedMapping;
  const savedKey = `novel-forge:edition-input:v1:${state.project_id}:${runId}:${revisionId}`;

  useEffect(() => {
    if (!runId) return;
    const token = ++generation.current;
    setError(""); setEdition(null);
    const query = new URLSearchParams({ project_id: state.project_id, workspace_id: state.workspace_id, book_run_id: runId, revision_id: revisionId });
    fetchJson<EditionState>(`/product/editor/editions?${query}`).then((value) => {
      if (token !== generation.current) return;
      setEdition(value); setPosition(0);
      const stored = localStorage.getItem(savedKey);
      const recovered = stored ? JSON.parse(stored) : null;
      const sameBase = !!recovered && !!value.revision && recovered.manifest_digest === value.revision.manifest.manifest_digest;
      setUnits(sameBase ? recovered.units : value.revision?.manifest.units || []);
      setPending(sameBase ? recovered.pending : null);
      setMapping(sameBase ? recovered.mapping || "" : "");
      setReason(sameBase ? recovered.reason || "" : "");
      setChangeKind(sameBase ? recovered.changeKind || "EXPRESSION" : "EXPRESSION");
      setInputSnapshot(sameBase ? recovered.inputSnapshot || "" : "");
      const bound = value.events?.findLast((event) => event.event_kind === "VALIDATION_BOUND" || event.event_kind === "VALIDATED");
      setValidationRun(String(bound?.content.validation_book_run_id || ""));
      if (sameBase) setNotice("已恢复尚未提交的整稿输入。原稿仍可读取。");
    }).catch((caught) => { if (token === generation.current) setError(String(caught)); });
    return () => {generation.current++;};
  }, [state.project_id, state.workspace_id, runId, revisionId, savedKey]);

  useEffect(() => {
    if (!revision) return;
    if (unsavedInputs || pending || reason || mapping || inputSnapshot || changeKind !== "EXPRESSION") localStorage.setItem(savedKey, JSON.stringify({ manifest_digest: revision.manifest.manifest_digest, units, pending, mapping, reason, changeKind, inputSnapshot }));
    else localStorage.removeItem(savedKey);
  }, [unsavedInputs, pending, revision, savedKey, units, mapping, reason, changeKind, inputSnapshot]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => { if (unsavedInputs || pending) {event.preventDefault(); event.returnValue = "";} };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [unsavedInputs, pending]);

  async function refresh(id = revisionId) {
    const value = await fetchJson<EditionState>(`/product/editor/editions?${new URLSearchParams({ ...scope, revision_id: id })}`);
    setEdition(value);
    if (!dirty) setUnits(value.revision?.manifest.units || []);
  }
  async function send(command: Pending) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setPending(command);
    try {
      const result = await fetchJson<{ revision_id: string; status: string }>("/product/editor/editions/commands", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(command),
      });
      localStorage.removeItem(savedKey); setPending(null);
      setNotice(`整稿操作已记录：${result.status || "版本已保存"}。编辑接纳不授予发布权限。`);
      if (result.revision_id !== revisionId) setRevisionId(result.revision_id);
      else await refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status >= 400 && caught.status < 500) setPending(null);
      setError(String(caught));
    } finally {lock.current = false; setBusy(false);}
  }
  function command(action: string, data: Record<string, unknown>) {
    void send({ ...scope, action, data, idempotency_key: crypto.randomUUID() });
  }
  function move(delta: number) {
    const next = position + delta;
    if (next < 0 || next >= units.length) return;
    setUnits((current) => { const copy = [...current]; [copy[position], copy[next]] = [copy[next], copy[position]]; return copy; });
    setPosition(next); setChangeKind("STRUCTURE");
  }
  async function startValidation() {
    if (!revision || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const result = await fetchJson<{ validation_book_run_id: string }>("/product/editor/editions/validation-start", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...scope, revision_id: revision.revision_id, input_snapshot_id: inputSnapshot }),
      });
      setValidationRun(result.validation_book_run_id);
      setNotice("已创建独立复核运行。正文按原生审改、Canon 和 Book 门控验证；进度可在生产工作台查看。");
      await refresh();
    } catch (caught) {setError(String(caught));} finally {lock.current = false; setBusy(false);}
  }
  const unit = units[position];
  return <section className="panel" aria-label="整稿版本编辑">
    <h2>整稿版本</h2>
    <p>从精确接纳稿创建编辑版本。修改、复核与正式切换各自保留记录，旧稿可随时查看和导出。</p>
    {notice ? <p role="status">{notice}</p> : null}{error ? <p role="alert" className="errorLine">{error}</p> : null}
    <div className="studioActions">
      <label>来源作品运行 <select aria-label="来源作品运行" value={runId} disabled={busy || unsavedInputs || !!pending} onChange={(event) => {setRunId(event.target.value); setRevisionId("");}}>
        {state.book_runs.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
      <label>整稿候选 <select aria-label="整稿候选" value={revisionId} disabled={busy || unsavedInputs || !!pending} onChange={(event) => setRevisionId(event.target.value)}>
        <option value="">当前接纳稿</option>{edition?.editions.map((item) => <option key={item.edition_id} value={item.current_revision_id}>版本 {item.version} · {item.edition_id.slice(-8)}</option>)}</select></label>
      <button className="secondaryButton" disabled={busy || unsavedInputs || !!pending || !edition} onClick={() => command("create", {
        base_manifest_digest: revision?.manifest.manifest_digest || edition?.source_manifest?.manifest_digest,
        ...(revision ? { base_revision_id: revision.revision_id } : {}),
      })}>{revision ? "从此版创建编辑分支" : "冻结已接纳正文"}</button>
      <button className="secondaryButton" disabled={busy} onClick={() => refresh().catch((caught) => setError(String(caught)))}>刷新并保留输入</button>
    </div>
    {revision && unit ? <>
      <p>正式版本：{edition?.head.selected_revision_id === revision.revision_id ? "当前所选版本" : "本候选未切换"} · {unsavedInputs ? "有未保存输入" : "输入已保存"}</p>
      <label>章节 <select aria-label="整稿章节" value={position} onChange={(event) => setPosition(Number(event.target.value))}>
        {units.map((item, index) => <option key={item.unit_id} value={index}>{index + 1}. {item.title}</option>)}</select></label>
      <textarea aria-label="整稿章节正文" className="richDraftEditor" rows={14} value={unit.text} disabled={busy || !!pending}
        onChange={(event) => setUnits((current) => current.map((item, index) => index === position ? { ...item, text: event.target.value } : item))} />
      <div className="studioActions"><button disabled={busy || !!pending || position === 0} onClick={() => move(-1)}>章节前移</button>
        <button disabled={busy || !!pending || position + 1 === units.length} onClick={() => move(1)}>章节后移</button></div>
      <label>变更类型 <select value={changeKind} onChange={(event) => setChangeKind(event.target.value)}>
        <option value="EXPRESSION">表达调整</option><option value="STRUCTURE">结构调整</option><option value="NARRATIVE_FACT">叙事事实变化</option><option value="UNKNOWN">影响待确定</option></select></label>
      <label>编辑理由 <textarea aria-label="整稿编辑理由" rows={2} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <label>已批准的生产输入快照（可选）<input aria-label="版本复核输入快照" value={inputSnapshot} onChange={(event) => setInputSnapshot(event.target.value)} /></label>
      <p>拆分章节超出原生产范围，或上层计划已换版时，先在生产工作台解析新输入，再填入快照身份。</p>
      <details><summary>章节与场景拆分、合并映射</summary><p>结构调整需保留精确来源范围和稳定身份，并绑定已批准的章节计划。保存时检查完整来源覆盖。</p>
        <button disabled={busy || !!pending} onClick={() => setMapping(JSON.stringify(units, null, 2))}>读取当前输入为映射</button>
        <textarea aria-label="整稿结构映射" rows={12} value={mapping} disabled={busy || !!pending} onChange={(event) => setMapping(event.target.value)} />
        <button disabled={busy || !!pending || !mapping} onClick={() => {try { const mapped = JSON.parse(mapping); if (!Array.isArray(mapped) || !mapped.length) throw new Error("映射必须是非空章节列表"); setUnits(mapped); setMapping(""); setPosition(0); setChangeKind("STRUCTURE"); } catch (caught) {setError(String(caught));}}}>应用结构映射到输入</button></details>
      {unappliedMapping ? <p>结构映射尚未应用；输入已暂存。请先应用映射，再保存或切换版本。</p> : null}
      <div className="studioActions">
        <button className="primaryButton" disabled={busy || !!pending || unappliedMapping || !dirty || !reason.trim()} onClick={() => command("save", {
          revision_id: revision.revision_id, expected_version: revision.edition.version, base_manifest_digest: revision.manifest.manifest_digest,
          units, reason, change_kind: changeKind,
        })}>保存整稿候选</button>
        {pending ? <button disabled={busy} onClick={() => send(pending)}>重试原请求</button> : null}
        <button disabled={busy || unsavedInputs || !!pending} onClick={startValidation}>开始版本复核</button>
        <button disabled={busy || unsavedInputs || !!pending || !validationRun} onClick={() => command("validate", { revision_id: revision.revision_id,
          expected_version: revision.edition.version, validation_book_run_id: validationRun })}>核验接纳结果</button>
        <button disabled={busy || unsavedInputs || !!pending || !reason.trim()} onClick={() => command("select", { revision_id: revision.revision_id,
          expected_head_version: edition?.head.version, reason })}>切换正式版本</button>
        <button disabled={busy || unsavedInputs || !!pending || !reason.trim() || edition?.head.selected_revision_id === revision.revision_id} onClick={() => command("reject", { revision_id: revision.revision_id,
          expected_version: revision.edition.version, reason })}>拒绝候选</button>
        <a href={`${API_BASE}/product/editor/editions/export?${new URLSearchParams({ ...scope, revision_id: revision.revision_id })}`} target="_blank" rel="noreferrer">导出此版正文</a>
      </div>
      {revision.manifest.impact ? <p>从第 {revision.manifest.impact.earliest_affected_position} 个位置开始重新核验；相关审读、签署和发布候选已失效。</p> : null}
      {edition?.validation_result ? <div>
        <p>原生审改结果已接纳，正式版本尚需单独切换。保存审改结果会保留当前提交稿及其前驱关系。</p>
        {edition.validation_result.diff.changes.map((item) => <details key={item.unit_id}><summary>审改差异：位置 {item.after_position ?? item.before_position}</summary><pre style={{ whiteSpace: "pre-wrap" }}>{item.diff}</pre></details>)}
        <button disabled={busy || unsavedInputs || !!pending || !reason.trim()} onClick={() => command("create", {
          source_validation_revision_id: revision.revision_id, validation_book_run_id: edition.validation_result?.book_run_id,
          expected_version: revision.edition.version, base_manifest_digest: edition.validation_result?.manifest.manifest_digest, reason,
        })}>保存审改后的版本</button>
      </div> : null}
      {edition?.diff?.changes.map((item) => <details key={item.unit_id}><summary>位置 {item.before_position ?? "新增"} → {item.after_position ?? "删除"}</summary><pre style={{ whiteSpace: "pre-wrap" }}>{item.diff}</pre></details>)}
      {revision.base_revision_id ? <button disabled={unsavedInputs || busy || !!pending} onClick={() => setRevisionId(revision.base_revision_id || "")}>查看原稿</button> : null}
      <ScreenplayPanel key={revision.revision_id} scope={scope} revisionId={revision.revision_id} units={revision.manifest.units} updates={edition?.adaptation_updates || []} />
      {edition?.events?.map((event) => <p key={event.event_id}>{event.event_kind} · {String(event.content.status || event.content.reason || "")}</p>)}
    </> : null}
  </section>;
}
