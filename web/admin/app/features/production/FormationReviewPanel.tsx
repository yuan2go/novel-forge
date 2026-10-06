"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../shared/api";
import { loadFormation, submitFormationDecision, type Formation, type FormationCandidate } from "./api";

type Decision = "SELECT" | "APPROVE" | "REJECT" | "REQUEST_CHANGES";
type Pending = {candidate_asset_version_id: string; candidate_content_hash: string; expected_version: number; idempotency_key: string; reason: string; decision: Decision};
const labels: Record<string, string> = {core_conflict: "核心冲突", reader_promise: "阅读承诺", narrative_engine: "叙事承载力", differentiation: "差异化", emotional_contract: "情绪承诺", thematic_question: "主题问题", ending_direction: "结局方向", protagonist_cost: "人物代价", constraints: "约束", characters: "人物驱动", character_cast: "人物驱动"};
export function describe(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(describe).join("；");
  if (value && typeof value === "object") return Object.entries(value).map(([key, item]) => `${labels[key] || key}：${describe(item)}`).join("；");
  return String(value ?? "");
}
export function FormationReviewPanel({formation, onChange}: {formation: Formation; onChange: (value: Formation) => void}) {
  const storageKey = `novel-forge:formation-review:${formation.formation_run_id}:${formation.current_stage}`;
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  useEffect(() => {
    try { const saved = JSON.parse(localStorage.getItem(storageKey) || "{}"); setNote(saved.note || ""); setPending(saved.pending || null); }
    catch { setError("未能读取上次候选确认，请保留本机记录。"); }
  }, [storageKey]);
  function retain(nextNote: string, nextPending: Pending | null) {
    try { localStorage.setItem(storageKey, JSON.stringify({note: nextNote, pending: nextPending})); setNote(nextNote); setPending(nextPending); return true; }
    catch { setError("未能保存候选决定。请先复制输入并恢复浏览器存储；原请求仍需核对。"); return false; }
  }
  async function send(body: Pending) {
    if (lock.current || !retain(body.reason, body)) return;
    lock.current = true; setBusy(true); setError("");
    try { onChange(await submitFormationDecision(formation.formation_run_id, body)); retain(body.reason, null); }
    catch (e) {
      setError(String(e));
      if (e instanceof ApiError && (e.status === 422 ||
        (e.status === 409 && ["STORY_FORMATION_REVIEW_CONFLICT", "STORY_FORMATION_REVIEW_SCOPE", "STORY_FORMATION_REVIEW_HASH_DRIFT"].includes(e.code || "")))) {
        try {
          const current = await loadFormation(formation.formation_run_id);
          localStorage.setItem(`${storageKey}:rejected:${body.idempotency_key}`, JSON.stringify(body));
          onChange(current); retain(body.reason, null);
        } catch { /* WHY: Without authoritative state, keep the original replay request. */ }
      }
    }
    finally {lock.current = false; setBusy(false);}
  }
  function decide(candidate: FormationCandidate, decision: Decision) {
    void send({candidate_asset_version_id: candidate.asset_version_id, candidate_content_hash: candidate.content_hash, expected_version: formation.version, idempotency_key: crypto.randomUUID(), reason: note.trim(), decision});
  }
  if (!formation.candidates?.length && !formation.author_review_history?.length) return null;
  return <section aria-label="设计候选确认">
    <h3>比较候选并确认设计</h3>
    <p>围绕本作品的作者意图、人物动机、因果、冲突潜力、差异化、篇幅适配和后续可写性比较。记录选择理由、优势、代价和难以区分之处；批准是本次方向决定，不能证明文学最佳。持久创作任务会在批准后继续推进；历史任务仍使用原恢复入口。</p>
    <label>选择理由 / 修改意见<textarea aria-label="选择理由 / 修改意见" value={note} disabled={busy || !!pending} onChange={e => retain(e.target.value, pending)} /></label>
    {formation.candidates?.map((candidate, index) => {
      const payload = candidate.content.candidate_payload || candidate.content;
      const selected = formation.recovery_instruction?.candidate_asset_version_id === candidate.asset_version_id;
      return <article className="panel" key={candidate.asset_version_id}>
        <h4>候选 {index + 1}{selected ? " · 当前选择" : ""}</h4>
        <dl>{Object.entries(payload as Record<string, unknown>).filter(([key]) => !["schema_version", "parent_bindings"].includes(key)).map(([key, value]) => <div key={key}><dt>{labels[key] || key}</dt><dd>{describe(value)}</dd></div>)}</dl>
        <p>资格：{describe(candidate.state.qualification) || "由设计审批检查"} · 审批：{describe(candidate.state.approval) || "待决定"}</p>
        <small>{candidate.content_hash}</small>
        <div className="actions">{([["SELECT", "选择此候选"], ["APPROVE", "批准此候选"], ["REJECT", "拒绝此候选"], ["REQUEST_CHANGES", "提交修改意见"]] as const).map(([decision, label]) => <button key={decision} disabled={busy || !!pending || !note.trim() || formation.lifecycle !== "WAITING_APPROVAL"} onClick={() => decide(candidate, decision)}>{label}</button>)}</div>
      </article>;
    })}
    {!!formation.recovery_instruction?.generation_failures?.length && <p role="status">部分方向生成未通过结构校验，原始失败已保留。请结合可用候选和不确定性决定；采用可用方向不表示它优于未完成的方向。</p>}
    {formation.recovery_instruction?.author_selection && <p>已保存决定：{formation.recovery_instruction.author_selection.decision} · {formation.recovery_instruction.author_selection.reason}</p>}
    {!!formation.author_review_history?.length && <details><summary>已保存的作者决定</summary>{formation.author_review_history.map(item => <div key={item.stage}><h4>{item.stage}</h4>{item.decisions.map((entry, index) => <p key={index}>{entry.decision} · {entry.reason} · 决定主体：{entry.actor_id}</p>)}</div>)}</details>}
    {pending && <button disabled={busy} onClick={() => send(pending)}>恢复候选决定（原幂等键）</button>}
    {error && <p role="alert" className="errorLine">{error}</p>}
  </section>;
}
