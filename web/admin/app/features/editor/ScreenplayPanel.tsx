"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, ApiError, fetchJson } from "../../shared/api";

type Scope = { project_id: string; workspace_id: string; book_run_id: string };
type SourceUnit = { unit_id: string; title: string };
type Result = { operation_id?: string; source_asset_version_id?: string; accepted_asset_version_id?: string;
  status?: string; outputs?: string[]; asset_type?: string; text?: string; content?: Record<string, unknown> };
type Pending = { path: string; body: Record<string, unknown> };
type CraftSuggestion = { knowledge_card_asset_version_id: string; content_hash: string;
  selected_content: { craft_mechanism?: { name: string; desired_reader_effect: string; scene_realization_guidance: string;
    prerequisites: string[]; contraindications: string[]; failure_modes: string[] } } };
type Knowledge = Record<string, unknown> & { recommended_craft_selection?: { selected: CraftSuggestion[] } };

export function ScreenplayPanel({ scope, revisionId, units, updates }: { scope: Scope; revisionId: string; units: SourceUnit[]; updates: Array<{asset_version_id: string; source_asset_version_id: string}> }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [plan, setPlan] = useState("[]");
  const [policy, setPolicy] = useState(JSON.stringify({ policy_version: "screenplay-adaptation.v1", must_preserve: [], allowed_changes: [],
    knowledge_contract: { reader_allowed_fact_ids: [], character_known_fact_ids: {} }, context_token_budget: 16000, max_revision_rounds: 2 }, null, 2));
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null);
  const [updateTaskId, setUpdateTaskId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [reviewId, setReviewId] = useState("");
  const [operationId, setOperationId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const storageKey = `novel-forge:screenplay:v1:${scope.project_id}:${revisionId}`;
  const restored = useRef(false);
  useEffect(() => {
    const stored = localStorage.getItem(storageKey);
    if (stored) {
      try {
        const value = JSON.parse(stored);
        setSelected(value.selected || []); setPlan(value.plan || "[]"); setPolicy(value.policy);
        setUpdateTaskId(value.updateTaskId || ""); setSourceId(value.sourceId || ""); setCandidateId(value.candidateId || ""); setReviewId(value.reviewId || "");
        setOperationId(value.operationId || ""); setAssetId(value.assetId || ""); setPending(value.pending || null);
      } catch { setError("无法读取本地恢复记录；请按原始任务编号查询服务器结果。"); }
    }
    restored.current = true;
  }, [storageKey]);
  useEffect(() => {
    if (restored.current) localStorage.setItem(storageKey, JSON.stringify({selected, plan, policy, sourceId, candidateId, reviewId, operationId, assetId, pending, updateTaskId}));
  }, [storageKey, selected, plan, policy, sourceId, candidateId, reviewId, operationId, assetId, pending, updateTaskId]);
  function consume(value: Result) {
    setResult(value);
    if (value.operation_id) setOperationId(value.operation_id);
    if (value.source_asset_version_id) setSourceId(value.source_asset_version_id);
    if (value.accepted_asset_version_id) setAssetId(value.accepted_asset_version_id);
  }
  async function send(request: Pending) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setPending(request);
    try {
      consume(await fetchJson<Result>(request.path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(request.body)}));
      setPending(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status >= 400 && caught.status < 500) setPending(null);
      setError(String(caught));
    } finally { lock.current = false; setBusy(false); }
  }
  async function query(operation = "", asset = "") {
    setError("");
    try {
      const value = await fetchJson<Result>(`/product/editor/screenplays?${new URLSearchParams({project_id: scope.project_id, operation_id: operation, asset_version_id: asset})}`);
      consume(value);
      if (asset) {
        setAssetId(asset);
        if (value.asset_type === "screenplay_candidate") setCandidateId(asset);
        if (value.asset_type === "screenplay_review") setReviewId(asset);
        if (value.asset_type === "screenplay_source_contract") setSourceId(asset);
      }
    } catch (caught) { setError(String(caught)); }
  }
  async function loadUpdate(update: {asset_version_id: string; source_asset_version_id: string}) {
    try {
      const value = await fetchJson<Result>(`/product/editor/screenplays?${new URLSearchParams({project_id: scope.project_id, asset_version_id: update.source_asset_version_id})}`);
      const content = value.content;
      if (!content) throw new Error("原改编来源不可读取");
      setSourceId(update.source_asset_version_id); setUpdateTaskId(update.asset_version_id);
      setPlan(JSON.stringify(content.scene_plan, null, 2)); setPolicy(JSON.stringify(content.policy, null, 2));
      setSelected((content.selected_unit_ids as string[]).filter((id) => units.some((unit) => unit.unit_id === id)));
      setCandidateId(""); setReviewId(""); setOperationId("");
    } catch (caught) {setError(String(caught));}
  }
  async function loadKnowledge() {
    const params = new URLSearchParams({...scope, revision_id: revisionId});
    selected.forEach((id) => params.append("selected_unit_ids", id));
    try {setKnowledge(await fetchJson<Knowledge>(`/product/editor/editions/knowledge?${params}`));}
    catch (caught) {setError(String(caught));}
  }
  function addCraftCard(card: CraftSuggestion) {
    try {
      const scenes = JSON.parse(plan);
      if (!Array.isArray(scenes) || !scenes.length || scenes.some((scene) => !scene || typeof scene !== "object" || Array.isArray(scene))) {
        throw new Error("请先填写场景计划，再选择需要采用的技法。");
      }
      const mechanism = card.selected_content.craft_mechanism;
      if (!mechanism) throw new Error("所选建议没有可用的技法合同。");
      setPlan(JSON.stringify(scenes.map((scene) => {
        const existing = scene.craft_uses ?? [];
        if (!Array.isArray(existing)) throw new Error("现有 craft_uses 必须是列表；请先修正，已有输入不会被覆盖。");
        if (existing.some((use) => use.knowledge_card_asset_version_id === card.knowledge_card_asset_version_id)) return scene;
        return {...scene, craft_uses: [...existing, {knowledge_card_asset_version_id: card.knowledge_card_asset_version_id,
          content_hash: card.content_hash, role: existing.length ? "SECONDARY" : "PRIMARY", sequence: existing.length + 1,
          required: false, adaptation_rationale: mechanism.scene_realization_guidance,
          prerequisite_resolution: mechanism.prerequisites.join("；"), intended_reader_effect: mechanism.desired_reader_effect,
          abandon_condition: mechanism.contraindications.join("；"), interference_risk: mechanism.failure_modes.join("；")}]};
      }), null, 2));
      setError("");
    } catch (caught) {setError(String(caught));}
  }
  function prepare() {
    try {
      void send({path: "/product/editor/screenplays/commands", body: {...scope, action: "prepare", idempotency_key: crypto.randomUUID(), data: {
        source_revision_id: revisionId, selected_unit_ids: selected, scene_plan: JSON.parse(plan), policy: JSON.parse(policy),
        ...(updateTaskId ? {predecessor_source_id: sourceId, update_task_asset_version_id: updateTaskId} : {}),
      }}});
    } catch (caught) {setError(String(caught));}
  }
  function stage(name: string) {
    void send({path: "/product/editor/screenplays/stages", body: {project_id: scope.project_id, workspace_id: scope.workspace_id,
      stage: name, source_asset_version_id: sourceId, idempotency_key: crypto.randomUUID(),
      ...(name !== "screenplay_generate" ? {candidate_asset_version_id: candidateId} : {}),
      ...(name === "screenplay_revision" ? {review_asset_version_id: reviewId} : {}),
    }});
  }
  return <details><summary>从此稿改编场景剧本</summary>
    <p>选择来源章节，写明场景安排、必须保留的事实和允许改编的范围。源稿换版会生成更新任务，旧剧本保留原来源。</p>
    {updates.map((update) => <button key={update.asset_version_id} disabled={busy || !!pending} onClick={() => loadUpdate(update)}>加载待更新的改编 {update.asset_version_id.slice(-8)}</button>)}
    {updateTaskId ? <p>正在更新原改编；请重新核对变化范围、场景映射和知情事实。</p> : null}
    {error ? <p role="alert" className="errorLine">{error}</p> : null}
    <fieldset disabled={busy || !!pending}><legend>改编范围</legend>{units.map((unit) => <label key={unit.unit_id}>
      <input type="checkbox" checked={selected.includes(unit.unit_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, unit.unit_id] : current.filter((id) => id !== unit.unit_id))} />{unit.title}
    </label>)}</fieldset>
    <button disabled={busy || !selected.length} onClick={loadKnowledge}>读取所选范围的人物与可知事实</button>
    {knowledge ? <details open><summary>精确来源的事实与知情范围</summary><pre style={{whiteSpace: "pre-wrap"}}>{JSON.stringify(knowledge, null, 2)}</pre></details> : null}
    {knowledge?.recommended_craft_selection?.selected.filter((card) => card.selected_content.craft_mechanism).map((card) =>
      <button key={card.knowledge_card_asset_version_id} disabled={busy || !!pending} onClick={() => addCraftCard(card)}>
        将建议技法「{card.selected_content.craft_mechanism?.name}」加入场景草案
      </button>)}
    <p>加入建议会保留现有场景与技法。请在草案中逐场核对适用理由、顺序、干扰风险和放弃条件，再冻结计划。</p>
    <label>场景计划 <textarea aria-label="剧本场景计划" rows={8} value={plan} disabled={busy || !!pending} onChange={(event) => setPlan(event.target.value)} /></label>
    <p>每场填写 scene_id、source_unit_ids、location、time、participants、dramatic_goal 和 required_fact_ids；参与人物使用作品中的稳定身份。craft_uses 保存批准技法的精确版本、场景适用理由及放弃条件。</p>
    <label>改编与知情范围 <textarea aria-label="剧本改编政策" rows={10} value={policy} disabled={busy || !!pending} onChange={(event) => setPolicy(event.target.value)} /></label>
    <div className="studioActions">
      <button disabled={busy || !!pending || !selected.length} onClick={prepare}>冻结改编来源与计划</button>
      <button disabled={busy || !!pending || !sourceId} onClick={() => stage("screenplay_generate")}>提交剧本生成</button>
      <button disabled={busy || !!pending || !candidateId} onClick={() => stage("screenplay_review")}>提交剧本审读</button>
      <button disabled={busy || !!pending || !reviewId || !candidateId} onClick={() => stage("screenplay_revision")}>按审读修订</button>
      <button disabled={busy || !!pending || !reviewId || !candidateId} onClick={() => send({path: "/product/editor/screenplays/commands", body: {
        ...scope, action: "accept", idempotency_key: crypto.randomUUID(), data: {source_asset_version_id: sourceId, candidate_asset_version_id: candidateId, review_asset_version_id: reviewId},
      }})}>核验并接纳剧本</button>
      {pending ? <button disabled={busy} onClick={() => send(pending)}>重试原请求</button> : null}
    </div>
    <p>来源 {sourceId || "尚未冻结"} · 候选 {candidateId || "尚未生成"} · 审读 {reviewId || "尚未完成"}</p>
    <label>运行编号 <input aria-label="剧本运行编号" value={operationId} onChange={(event) => setOperationId(event.target.value)} /></label>
    <div className="studioActions"><button disabled={!operationId || busy} onClick={() => query(operationId)}>查询运行</button>
      <button disabled={!operationId || busy || !!pending} onClick={() => send({path: "/product/editor/screenplays/resume", body: {project_id: scope.project_id, operation_id: operationId}})}>继续原运行</button></div>
    <label>产物编号 <input aria-label="剧本产物编号" value={assetId} onChange={(event) => setAssetId(event.target.value)} /></label>
    <button disabled={!assetId || busy} onClick={() => query("", assetId)}>读取产物并采用其编号</button>
    {result?.outputs?.map((id) => <button key={id} onClick={() => query("", id)}>读取本次产物 {id.slice(-8)}</button>)}
    {result?.text ? <><pre style={{whiteSpace: "pre-wrap"}}>{result.text}</pre><a href={`${API_BASE}/product/editor/screenplays/export?${new URLSearchParams({project_id: scope.project_id, asset_version_id: assetId})}`} target="_blank" rel="noreferrer">导出剧本</a></> : null}
    {result ? <details><summary>运行与审读记录</summary><pre style={{whiteSpace: "pre-wrap"}}>{JSON.stringify(result, null, 2)}</pre></details> : null}
  </details>;
}
