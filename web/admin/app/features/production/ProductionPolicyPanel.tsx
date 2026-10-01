"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, fetchJson } from "../../shared/api";
import { loadCreativeInput, saveCreativeInput, type Book, type ContentOperation, type Profile, type Workspace } from "./api";

type Choices = { name: string; target: number; draftProfile: string; draftBudget: number; qualityBudget: number; craft: string; neighbours: boolean; previous: number; sourceBudget: number; actors: string[]; actorMode: string; worldBudget: number; reason: string };
type Rejection = {body: Record<string, unknown>; status: number; detail: string; rejectedAt: string};
type Saved = { rejections?: Rejection[]; conflict?: boolean; choices: Choices; pending: Record<string, unknown> | null; operationId: string; completedAssetId?: string };
const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
function initial(profile?: Profile): Choices {
  const content = profile?.content || {}, context = object(content.chapter_context_policy), review = object(content.cross_chapter_review_policy), actor = object(content.world_actor_experiment), world = object(content.world_production_policy);
  return { name: `${String(content.profile_id || "作者生产配置")} · 新版`, target: Number(content.target_chapter_count || 1), draftProfile: String(context.draft_profile || "draft-context-profile-v2"), draftBudget: Number(context.draft_token_budget || 16000), qualityBudget: Number(context.quality_token_budget || 16000), craft: String(object(content.craft_budget_policy).schema_version || "narrative-craft-budget.v1"), neighbours: !!content.cross_chapter_review_policy, previous: Number(review.maximum_previous_chapters || 2), sourceBudget: Number(review.source_token_budget || 4000), actors: Array.isArray(actor.actor_ids) ? actor.actor_ids.map(String) : [], actorMode: content.world_actor_experiment ? "KEEP" : "NONE", worldBudget: Number(world.context_token_budget || 8192), reason: "" };
}
export function PolicySummary({content}: {content: Record<string, unknown>}) {
  const context = object(content.chapter_context_policy), world = object(content.world_production_policy), actor = object(content.world_actor_experiment), review = object(content.cross_chapter_review_policy), craft = object(content.craft_budget_policy);
  return <dl>
    <dt>正文 Context</dt><dd>{context.draft_profile ? `${context.draft_profile}，${context.draft_token_budget} tokens；审读 ${context.quality_token_budget} tokens` : "此历史配置未显式冻结 Context；实际值请查看章节准备记录，不能推断为当前服务默认。"}</dd>
    <dt>技法策略</dt><dd>{String(craft.schema_version || "narrative-craft-budget.v1（兼容默认）")}；所用技法仍须来自获准知识与章节计划。</dd>
    <dt>世界与角色</dt><dd>{String(world.version || "world-production-policy.v1（兼容默认）")}；{actor.version ? `${actor.version}，角色 ${Array.isArray(actor.actor_ids) ? actor.actor_ids.join("、") : "未选择"}` : "未启用 Actor"}</dd>
    <dt>跨章正文审读</dt><dd>{review.version ? `前 ${review.maximum_previous_chapters || 2} 章，来源预算 ${review.source_token_budget} tokens；实际覆盖随回执记录` : "未启用跨章正文窗口；章节原有审稿仍保留"}</dd>
    <dt>模型与额度</dt><dd>由已激活 Pack、任务 Router 与独立预算授权决定。保存此配置不追加调用额度，也不表示模型已准入。</dd>
  </dl>;
}
export function ProductionPolicyPanel({project, book, profile, characters, onRefresh, onSelect}: {project: string; book: Book; profile?: Profile; characters: Workspace["approved_characters"]; onRefresh: () => Promise<void>; onSelect: (id: string) => void}) {
  const storageKey = `novel-forge:production-policy:${project}:${book.book_id}:${profile?.asset_version_id || "new"}`;
  const [saved, setSaved] = useState<Saved>({choices: initial(profile), pending: null, operationId: ""});
  const [ready, setReady] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [operation, setOperation] = useState<ContentOperation | null>(null);
  const [conflictingOperation, setConflictingOperation] = useState<ContentOperation | null>(null);
  const lock = useRef(false), consumed = useRef("");
  useEffect(() => { try {setSaved(JSON.parse(localStorage.getItem(storageKey) || "null") || {choices: initial(profile), pending: null, operationId: ""});} catch {setError("配置草稿无法读取，请先保留本地记录。");} setReady(true); }, [storageKey]);
  useEffect(() => {if (ready) localStorage.setItem(storageKey, JSON.stringify(saved));}, [storageKey, ready, saved]);
  function retain(value: Saved) {localStorage.setItem(storageKey, JSON.stringify(value)); setSaved(value);}
  useEffect(() => {
    if (!saved.operationId) return;
    let active = true;
    const poll = async () => {try {const value = await loadCreativeInput(project, saved.operationId); if (!active) return; setOperation(value); const output = value.outputs?.[0]; if (value.status === "SUCCEEDED" && output && consumed.current !== value.operation_id && saved.completedAssetId !== output.asset_version_id) {consumed.current = value.operation_id; retain({...saved, completedAssetId: output.asset_version_id}); await onRefresh(); if (active) onSelect(output.asset_version_id);}} catch(e) {if (active) setError(String(e));}};
    void poll(); const timer = setInterval(poll, 5000); return () => {active = false; clearInterval(timer);};
  }, [project, saved.operationId]);
  const choices = saved.choices, disabled = busy || !!saved.pending || (!!saved.operationId && !["FAILED_FINAL", "DEAD_LETTER", "CANCELLED", "SUCCEEDED"].includes(operation?.status || ""));
  function change<K extends keyof Choices>(key: K, value: Choices[K]) {setSaved(current => ({...current, choices: {...current.choices, [key]: value}}));}
  async function submit(body: Record<string, unknown>) {
    if (lock.current) return; lock.current = true; setBusy(true); setError(""); retain({...saved, pending: body});
    try {const result = await saveCreativeInput(body); setOperation(result); retain({...saved, pending: null, conflict: false, operationId: result.operation_id});}
    catch(e) {
      setError(String(e));
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        const rejected = {body, status: e.status, detail: e.message, rejectedAt: new Date().toISOString()};
        const uncommitted = [400, 401, 403, 404, 422].includes(e.status);
        retain({...saved, pending: uncommitted ? null : body, conflict: e.status === 409, rejections: [...(saved.rejections || []), rejected]});
      }
    } finally {lock.current = false; setBusy(false);}
  }
  async function inspectConflict() {
    if (!saved.pending || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const rows = await fetchJson<Array<{operation_id: string; definition_name: string}>>(`/product/content-authority/operations?${new URLSearchParams({project_id: project, idempotency_key: String(saved.pending.idempotency_key), limit: "2"})}`);
      if (rows.length !== 1 || rows[0].definition_name !== "book.production_profile.author") throw new Error("未找到唯一的本项目配置任务。原请求仍保留；请核对冲突原因，不自动另发新请求。");
      setConflictingOperation(await loadCreativeInput(project, rows[0].operation_id));
    } catch(e) {setError(String(e));} finally {lock.current = false; setBusy(false);}
  }
  async function cancelRetryable() {
    if (!operation || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      await fetchJson(`/product/content-authority/operations/${encodeURIComponent(operation.operation_id)}/cancel`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({project_id: project, idempotency_key: `author-config-cancel:${operation.operation_id}`, reason: "作者更正配置前停止原可重试任务；保留失败历史。"})});
      setOperation(await loadCreativeInput(project, operation.operation_id));
    } catch(e) {setError(String(e));} finally {lock.current = false; setBusy(false);}
  }
  function save() {
    const id = crypto.randomUUID();
    const content: Record<string, unknown> = {...profile?.content, type: "production_profile", book_id: book.book_id, profile_id: choices.name.trim(), target_chapter_count: choices.target, language_contract: profile?.content.language_contract || {language: "zh", script: "Hans"}, safe_summary: choices.reason.trim(), structured_facts: [], authority_boundary: "FUTURE_INTENT", author_configuration_version: "book-author-configuration.v1", chapter_context_policy: {version: "book-chapter-context.v1", draft_profile: choices.draftProfile, draft_token_budget: choices.draftBudget, quality_token_budget: choices.qualityBudget}, craft_budget_policy: object(profile?.content.craft_budget_policy).schema_version === choices.craft ? profile?.content.craft_budget_policy : {schema_version: choices.craft}, author_configuration_source: profile ? {asset_version_id: profile.asset_version_id, content_hash: profile.content_hash} : null};
    if (choices.neighbours) content.cross_chapter_review_policy = {version: "accepted-prose-neighbours.v1", maximum_previous_chapters: choices.previous, source_token_budget: choices.sourceBudget}; else delete content.cross_chapter_review_policy;
    if (choices.actorMode === "PERSISTENT") {content.world_actor_experiment = {version: "world-actor-experiment.v2", actor_ids: choices.actors, max_rounds: 1, max_actions_per_actor: 1, max_intent_steps: 4}; content.world_production_policy = {version: choices.draftProfile.endsWith("v4") ? "world-production-policy.v4" : "world-production-policy.v3", max_candidates: choices.actors.length, max_paths_per_candidate: 1, max_preparation_steps: 1, planning_window_chapters: 1, max_provider_stages: choices.actors.length + 2, context_token_budget: choices.worldBudget, max_world_time_advance: Number(object(profile?.content.world_production_policy).max_world_time_advance || 1000)};}
    if (choices.actorMode === "NONE") {delete content.world_actor_experiment; content.world_production_policy = {version: choices.draftProfile.endsWith("v4") ? "world-production-policy.v4" : "world-production-policy.v1", context_token_budget: choices.worldBudget};}
    void submit({project_id: project, workspace_id: book.workspace_id, definition_name: "book.production_profile.author", idempotency_key: id, payload: {content}});
  }
  return <section className="panel"><h2>确认新的生产策略</h2>
    <p>{profile ? `基于配置 ${String(profile.content.profile_id || profile.asset_version_id)} 创建新版本。` : "填写本书的显式生产策略。"}保存经现有 Content Authority 校验后，再解析新快照。已提交的生产记录和章节继续使用原冻结版本。</p>
    <div className="formGrid wide">
      <label>配置名称<input aria-label="配置名称" value={choices.name} disabled={disabled} onChange={e => change("name", e.target.value)} /></label>
      <label>作品目标章数<input aria-label="配置目标章数" type="number" min={1} value={choices.target} disabled={disabled} onChange={e => change("target", Number(e.target.value))} /></label>
      <label>正文 Context 策略<select aria-label="正文 Context 策略" value={choices.draftProfile} disabled={disabled} onChange={e => {change("draftProfile", e.target.value); if (e.target.value.endsWith("v2") && choices.draftBudget > 16000) change("draftBudget", 16000);}}><option value="draft-context-profile-v2">v2 · 上限 16000</option><option value="draft-context-profile-v3">v3 · 上限 24000</option><option value="draft-context-profile-v4">v4 · 按任务选择，上限 512000</option></select></label>
      <label>正文 Context tokens<input aria-label="正文 Context tokens" type="number" min={1} max={choices.draftProfile.endsWith("v4") ? 512000 : choices.draftProfile.endsWith("v3") ? 24000 : 16000} value={choices.draftBudget} disabled={disabled} onChange={e => change("draftBudget", Number(e.target.value))} /></label>
      <label>审读 Context tokens<input aria-label="审读 Context tokens" type="number" min={1} value={choices.qualityBudget} disabled={disabled} onChange={e => change("qualityBudget", Number(e.target.value))} /></label>
      <label>技法策略<select aria-label="技法策略" value={choices.craft} disabled={disabled} onChange={e => change("craft", e.target.value)}>{[1,2,3,4].map(v => <option key={v} value={`narrative-craft-budget.v${v}`}>Craft v{v}{v === 4 ? " · 有界重新选择与阶段延续" : " · 保留对应合同"}</option>)}</select></label>
      <label><input type="checkbox" checked={choices.neighbours} disabled={disabled} onChange={e => change("neighbours", e.target.checked)} />审读时读取已接纳的前文</label>
      {choices.neighbours && <><label>前文章数<input aria-label="审读前文章数" type="number" min={1} value={choices.previous} disabled={disabled} onChange={e => change("previous", Number(e.target.value))} /></label><label>前文来源 tokens<input aria-label="前文来源 tokens" type="number" min={1} value={choices.sourceBudget} disabled={disabled} onChange={e => change("sourceBudget", Number(e.target.value))} /></label></>}
      <label>Actor 参与<select aria-label="Actor 参与" value={choices.actorMode} disabled={disabled} onChange={e => {change("actorMode", e.target.value); if (e.target.value === "NONE" && !choices.draftProfile.endsWith("v4") && choices.worldBudget > 16000) change("worldBudget", 16000);}}>{profile?.content.world_actor_experiment ? <option value="KEEP">保留来源配置的角色与合同</option> : null}<option value="NONE">不启用 Actor</option><option value="PERSISTENT" disabled={!characters?.length}>选择已有角色的持续意图</option></select></label>
      {choices.actorMode === "PERSISTENT" && <fieldset><legend>本书已批准角色（最多三位）</legend>{characters?.map(character => <label key={character.character_id}><input type="checkbox" checked={choices.actors.includes(character.character_id)} disabled={disabled || (!choices.actors.includes(character.character_id) && choices.actors.length >= 3)} onChange={e => change("actors", e.target.checked ? [...choices.actors, character.character_id] : choices.actors.filter(id => id !== character.character_id))} />{character.name}</label>)}<p>沿用批准的角色事实；没有合法角色知识时，World 准备会明确停止。</p></fieldset>}
      {choices.actorMode !== "KEEP" && <label>World Context tokens<input aria-label="World Context tokens" type="number" min={1} max={choices.draftProfile.endsWith("v4") ? 512000 : choices.actorMode === "PERSISTENT" ? 24000 : 16000} value={choices.worldBudget} disabled={disabled} onChange={e => change("worldBudget", Number(e.target.value))} /></label>}
    </div>
    <label>本次选择依据<textarea aria-label="策略选择依据" value={choices.reason} disabled={disabled} onChange={e => change("reason", e.target.value)} placeholder="说明当前场景需要的上下文、技法与角色参与；保持不需要的能力关闭。" /></label>
    <button disabled={disabled || !choices.name.trim() || !choices.reason.trim() || choices.target < 1 || (choices.actorMode === "PERSISTENT" && !choices.actors.length)} onClick={save}>确认并保存新配置</button>
    {saved.pending && !saved.conflict && <button disabled={busy} onClick={() => submit(saved.pending!)}>恢复配置提交（原输入和幂等键）</button>}
    {saved.pending && saved.conflict && <div><p>服务器报告冲突。原请求与幂等键 {String(saved.pending.idempotency_key)} 保留；先核对已存在的任务，不能用新输入覆盖原请求。</p><button disabled={busy} onClick={inspectConflict}>按原幂等键查询配置任务</button>
      {conflictingOperation && <div><p>已存在任务：{conflictingOperation.operation_id} · {conflictingOperation.status}。跟踪的是服务器已提交的原输入；当前修改和拒绝记录继续保留。</p><button disabled={busy} onClick={() => {setOperation(conflictingOperation); retain({...saved, pending: null, conflict: false, operationId: conflictingOperation.operation_id}); setConflictingOperation(null);}}>跟踪已提交的原任务</button></div>}
    </div>}
    {operation && <p role="status">配置任务：{operation.status} · {operation.operation_id}{["FAILED_FINAL", "DEAD_LETTER", "CANCELLED"].includes(operation.status) ? "；原任务已停止，可更正输入后提交新请求，历史保留。" : operation.status === "FAILED_RETRYABLE" ? "；原任务仍可重试，更正前先停止它。" : ""}</p>}
    {operation?.status === "FAILED_RETRYABLE" && <button disabled={busy} onClick={cancelRetryable}>停止原任务后更正配置</button>}
    {!!saved.rejections?.length && <details><summary>配置提交拒绝记录（{saved.rejections.length}）</summary>{saved.rejections.map((item,index) => <p key={index}>{item.rejectedAt} · HTTP {item.status} · 幂等键 {String(item.body.idempotency_key)} · {item.detail}</p>)}</details>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
