"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, fetchJson } from "../../shared/api";
import type { Book } from "./api";

type Sample = {asset_version_id: string; content_hash: string; content: Record<string, unknown>; reference_contract: {dimensions: string[]; protocol_version: string; evaluation_version: string}};
type Workspace = {samples: Sample[]; actor_id: string; can_annotate: boolean};
type Pending = Record<string, unknown> & {idempotency_key: string};
type Draft = {sample: string; dimension: string; status: string; score: string; confidence: string; role: string; scope: string; start: string; end: string; quote: string; rationale: string; strengths: string; blind: boolean; confirmed: boolean; pending: Pending | null};
const initial: Draft = {sample: "", dimension: "", status: "", score: "", confidence: "", role: "", scope: "CHAPTER", start: "", end: "", quote: "", rationale: "", strengths: "", blind: false, confirmed: false, pending: null};
const fields: Record<string, string> = {core_conflict: "核心冲突", objective: "创作目标", target_reader: "目标读者", core_desire: "人物欲望", core_fear: "人物恐惧", narrative_engine: "叙事承载力", differentiation: "差异化", emotional_contract: "情感承诺", constraints: "约束", prohibited_outcomes: "禁止结果", style_profile: "风格", genre: "题材", subgenre: "子类型", why_worth_writing: "创作价值", serialization_potential: "持续承载力"};
const dimensions: Record<string, string> = {CORE_CONFLICT_CLARITY: "核心冲突是否清晰", READER_FIT: "是否符合目标读者", DIFFERENTIATION: "差异是否有内容依据", SERIALIZATION_CAPACITY: "能否持续承载叙事", EMOTIONAL_CONTRACT: "情感承诺是否明确"};
function readable(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(readable).join("\n");
  if (value && typeof value === "object") return Object.entries(value).map(([k, v]) => `${fields[k] || k}：${readable(v)}`).join("\n");
  return String(value ?? "");
}
export function ReferenceReviewPanel({project, book}: {project: string; book: Book}) {
  const storageKey = `novel-forge:reference-review:${project}:${book.book_id}`;
  const [draft, setDraft] = useState<Draft>(initial);
  const [workspace, setWorkspace] = useState<Workspace>({samples: [], actor_id: "", can_annotate: false});
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [canCorrect, setCanCorrect] = useState(false);
  const lock = useRef(false);
  useEffect(() => {
    try {setDraft({...initial, ...JSON.parse(localStorage.getItem(storageKey) || "{}")});}
    catch {setError("本机评阅草稿读取失败，请保留原记录。");}
    let active = true;
    fetchJson<Workspace>(`/product/content-authority/reference-samples?${new URLSearchParams({project_id: project, book_id: book.book_id})}`)
      .then(value => {if (active) setWorkspace(value);}).catch(e => {if (active) setError(String(e));});
    return () => {active = false;};
  }, [storageKey, project, book.book_id]);
  function retain(next: Draft) {
    try {localStorage.setItem(storageKey, JSON.stringify(next)); setDraft(next); return true;}
    catch {setError("本机无法保存评阅草稿。请先复制输入内容并恢复浏览器存储；本次未提交。"); return false;}
  }
  function change<K extends keyof Draft>(key: K, value: Draft[K]) {retain({...draft, [key]: value});}
  function choose(sample: string) {
    try {
      if (draft.sample) localStorage.setItem(`${storageKey}:sample:${draft.sample}`, JSON.stringify(draft));
      retain({...initial, ...JSON.parse(localStorage.getItem(`${storageKey}:sample:${sample}`) || "{}"), sample});
    } catch {setError("切换样本前未能保存原评阅，请先复制输入内容。");}
  }
  function archive(next: Draft, reason: string) {
    if (draft.pending) localStorage.setItem(`${storageKey}:history:${draft.pending.idempotency_key}`, JSON.stringify({request: draft.pending, reason}));
    retain(next); setCanCorrect(false);
  }
  async function send(body: Pending) {
    if (lock.current) return;
    if (!retain({...draft, pending: body})) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); setCanCorrect(false);
    try {
      const result = await fetchJson<{operation_id: string; asset_version_id: string; status: string}>("/product/content-authority/reference-evaluations", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      localStorage.setItem(`${storageKey}:receipt:${body.idempotency_key}`, JSON.stringify(result));
      retain({...draft, pending: null, confirmed: false}); setNotice(`评阅已保存：${result.status} · ${result.asset_version_id}。仍需独立评阅和裁决，样本未被接纳。`);
    } catch (e) {
      setError(String(e));
      if (e instanceof ApiError && [403, 422].includes(e.status)) {
        localStorage.setItem(`${storageKey}:history:${body.idempotency_key}`, JSON.stringify({request: body, reason: String(e)}));
        retain({...draft, pending: null});
      }
    } finally {lock.current = false; setBusy(false);}
  }
  async function lookup() {
    if (!draft.pending || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const rows = await fetchJson<Array<{operation_id: string; status: string}>>(`/product/content-authority/operations?${new URLSearchParams({project_id: project, idempotency_key: `author-reference:${draft.pending.idempotency_key}`})}`);
      if (!rows.length) {setCanCorrect(true); setNotice("未找到已接收的原评阅任务。可保留原请求记录后更正，或恢复原请求。");}
      else {
        setNotice(`原评阅任务：${rows[0].status} · ${rows[0].operation_id}`);
        if (rows[0].status === "SUCCEEDED") archive({...draft, pending: null, confirmed: false}, "Native operation confirms success");
        else if (["FAILED_FINAL", "CANCELLED", "DEAD_LETTER"].includes(rows[0].status)) setCanCorrect(true);
      }
    } catch (e) {setError(String(e));} finally {lock.current = false; setBusy(false);}
  }
  const sample = workspace.samples.find(s => s.asset_version_id === draft.sample);
  const locked = busy || !!draft.pending;
  const valid = sample && draft.dimension && draft.status && draft.score !== "" && Number(draft.score) >= 0 && Number(draft.score) <= 100 && draft.confidence !== "" && Number(draft.confidence) >= 0 && Number(draft.confidence) <= 1 && draft.role && Number.isInteger(Number(draft.start)) && Number(draft.start) > 0 && Number.isInteger(Number(draft.end)) && Number(draft.end) >= Number(draft.start) && (draft.scope !== "CHAPTER" || draft.end === draft.start) && draft.quote.trim() && draft.rationale.trim() && draft.strengths.trim() && draft.confirmed;
  function submit() {
    if (!sample || !valid) return;
    void send({project_id: project, book_id: book.book_id, asset_version_id: sample.asset_version_id, content_hash: sample.content_hash, dimension: draft.dimension, status: draft.status, score: Number(draft.score), confidence: Number(draft.confidence), evaluator_identity_class: draft.role, scope_type: draft.scope, chapter_start: Number(draft.start), chapter_end: Number(draft.end), quote: draft.quote, rationale: draft.rationale, preserve_strengths: draft.strengths, blind: draft.blind, human_confirmation: true, idempotency_key: crypto.randomUUID()});
  }
  return <section className="panel" aria-label="真实样本人工评阅">
    <h2>真实样本人工评阅</h2>
    <p>诊断样本保留为未接纳候选。请本人阅读并判断，每项意见保存原文依据与应保留的优点。此表单不展示生成模型和其他评阅结果；看过这些信息时请勿声明盲评。</p>
    {!workspace.can_annotate && <p>当前身份可查询；提交需要有权限的真人操作者登录。</p>}
    {!workspace.samples.length && <p>当前作品尚无可评阅的原生诊断候选。</p>}
    <label>评阅样本<select aria-label="评阅样本" disabled={locked} value={draft.sample} onChange={e => choose(e.target.value)}><option value="">选择样本</option>{workspace.samples.map((s, i) => <option key={s.asset_version_id} value={s.asset_version_id}>样本 {i + 1} · {s.content_hash.slice(-10)}</option>)}</select></label>
    {sample && <>
      <article aria-label="样本完整内容"><dl>{Object.entries(sample.content).filter(([k]) => !["schema_version", "constraint_envelope", "foundation_parent_bindings"].includes(k)).map(([k, value]) => <div key={k}><dt>{fields[k] || k}</dt><dd style={{whiteSpace: "pre-wrap"}}>{readable(value)}</dd></div>)}</dl></article>
      <p>当前评阅身份：{workspace.actor_id} · 原稿 hash：{sample.content_hash}</p>
      <fieldset disabled={locked || !workspace.can_annotate}><legend>本人评阅</legend>
        <label>评阅维度<select aria-label="评阅维度" value={draft.dimension} onChange={e => change("dimension", e.target.value)}><option value="">选择维度</option>{sample.reference_contract.dimensions.map(d => <option key={d} value={d}>{dimensions[d.split(":").at(-1)!] || d}</option>)}</select></label>
        <label>判断<select aria-label="评阅判断" value={draft.status} onChange={e => change("status", e.target.value)}><option value="">请选择</option><option value="PASSED">符合此项要求</option><option value="FAILED">此项存在实质问题</option></select></label>
        <label>分数（0—100）<input aria-label="评阅分数" type="number" min={0} max={100} value={draft.score} onChange={e => change("score", e.target.value)} /></label>
        <label>判断把握（0—1）<input aria-label="判断把握" type="number" min={0} max={1} step={0.05} value={draft.confidence} onChange={e => change("confidence", e.target.value)} /></label>
        <label>本人评阅角色<select aria-label="本人评阅角色" value={draft.role} onChange={e => change("role", e.target.value)}><option value="">请选择真实角色</option><option value="AUTHOR_EDITOR">作者 / 编辑</option><option value="PROFESSIONAL_EDITOR">专业编辑</option><option value="EXPERIENCED_READER">有经验的读者</option><option value="GENERAL_READER">普通读者</option></select></label>
        <label>评阅范围<select aria-label="评阅范围" value={draft.scope} onChange={e => change("scope", e.target.value)}><option value="CHAPTER">单章计划范围</option><option value="ARC">跨章计划范围</option></select></label>
        <label>计划起始章<input aria-label="评阅起始章" type="number" min={1} value={draft.start} onChange={e => change("start", e.target.value)} /></label>
        <label>计划结束章<input aria-label="评阅结束章" type="number" min={1} value={draft.end} onChange={e => change("end", e.target.value)} /></label>
        <p>范围表示这次判断覆盖的计划，不表示这些章节已经完成。</p>
        <label>原文依据<textarea aria-label="原文依据" value={draft.quote} onChange={e => change("quote", e.target.value)} /></label>
        <label>判断理由 / 修订目标<textarea aria-label="判断理由" value={draft.rationale} onChange={e => change("rationale", e.target.value)} /></label>
        <label>应保留的优点<textarea aria-label="应保留的优点" value={draft.strengths} onChange={e => change("strengths", e.target.value)} /></label>
        <label><input aria-label="本人未见模型身份或其他评价" type="checkbox" checked={draft.blind} onChange={e => change("blind", e.target.checked)} />本人评阅前未见生成模型身份或其他评价</label>
        <label><input aria-label="确认本人完成评阅" type="checkbox" checked={draft.confirmed} onChange={e => change("confirmed", e.target.checked)} />以上判断由本人完成，角色与盲评声明属实</label>
        <button className="primaryButton" disabled={!valid} onClick={submit}>保存本人评阅</button>
      </fieldset>
    </>}
    {draft.pending && <div className="actions"><button disabled={busy} onClick={() => send(draft.pending!)}>恢复评阅提交（原幂等键）</button><button disabled={busy} onClick={lookup}>查询原评阅任务</button>{canCorrect && <button disabled={busy} onClick={() => archive({...draft, pending: null}, "No admitted operation found; author chose to correct")}>保留原请求后更正</button>}</div>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="errorLine">{error}</p>}
  </section>;
}
