"use client";

import { useEffect, useRef, useState } from "react";
import { fetchJson } from "../../shared/api";
import type { Book, EditorialControl } from "./api";

export const controlModes: Record<string, string> = {AUTO: "自动推进（仍受资格、预算与质量门禁约束）", REVIEW_MAJOR_DECISION: "重大决策需确认", REVIEW_PLAN: "层级计划需确认", REVIEW_CHAPTER: "章节最终候选需确认", REVIEW_REALITY_COMMIT: "叙事事实接纳需确认", MANUAL_DIRECTOR: "导演决策需人工确认"};
type Saved = {mode: string; pending: Record<string, unknown> | null};
export function EditorialControlPanel({project, book, current, onRefresh}: {project: string; book: Book; current?: EditorialControl | null; onRefresh: () => Promise<void>}) {
  const key = `novel-forge:editorial-control:${project}`;
  const [saved, setSaved] = useState<Saved>({mode: "", pending: null});
  const [busy, setBusy] = useState(false), [ready, setReady] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const lock = useRef(false);
  useEffect(() => {try {setSaved(JSON.parse(localStorage.getItem(key) || "null") || {mode: "", pending: null});} catch {setError("审阅策略草稿读取失败。");} setReady(true);}, [key]);
  useEffect(() => {if (ready) localStorage.setItem(key, JSON.stringify(saved));}, [saved, ready, key]);
  function retain(value: Saved) {localStorage.setItem(key, JSON.stringify(value)); setSaved(value);}
  async function send(body: Record<string, unknown>) {
    if (lock.current) return; lock.current = true; setBusy(true); setError(""); setNotice(""); retain({...saved, pending: body});
    try {await fetchJson("/product/production/book-authority/policies/book-control", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}); retain({...saved, pending: null}); await onRefresh(); setNotice("项目审阅策略已保存。已冻结的章节继续使用原策略。");} catch(e) {setError(String(e));} finally {lock.current = false; setBusy(false);}
  }
  function save() {const id = crypto.randomUUID(); void send({project_id: project, workspace_id: book.workspace_id, actor_id: "", policy: {policy_version: `book-control:author:${id}`, mode: saved.mode}, idempotency_key: id, trace_id: `trace:${id}`, correlation_id: id});}
  return <section className="panel"><h2>项目审阅确认方式</h2>
    <p>作用于此项目以后首次冻结的章节，包括项目内其他作品；已在途章节和恢复请求保留各自原策略。此操作不修改 Formation 的确认模式，不释放项目暂停，也不增加预算。</p>
    <p>当前项目选择：{current ? controlModes[current.policy.mode] || current.policy.mode : "未设置；首次冻结时使用原生 AUTO 默认"}{current && ` · ${current.policy.policy_version} · ${current.content_hash}`}</p>
    <label>新的项目审阅方式<select aria-label="新的项目审阅方式" value={saved.mode} disabled={busy || !!saved.pending} onChange={e => setSaved({...saved, mode: e.target.value})}><option value="">保留当前设置</option>{Object.entries(controlModes).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <button disabled={busy || !!saved.pending || !saved.mode} onClick={save}>确认项目范围并保存审阅方式</button>
    {saved.pending && <button disabled={busy} onClick={() => send(saved.pending!)}>恢复审阅策略提交（原幂等键）</button>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
