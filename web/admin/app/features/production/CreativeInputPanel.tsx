"use client";

import { useEffect, useRef, useState } from "react";
import {CurrentManuscriptPanel} from "./CurrentManuscriptPanel";
import { FormationReviewPanel } from "./FormationReviewPanel";
import { EditorialLearningInput } from "./EditorialLearningInput";
import { eligibleEditorialCards, editorialProblems, editorialBriefExtension, type EditorialLearning, type EditorialCard } from "./editorial-learning";
import { ApiError, fetchJson } from "../../shared/api";
import type { ProjectRow } from "../../shared/types";
import { createAuthorBook, createAuthorWorkspace, loadProductionProjects, saveCreativeInput, loadCreativeInput, startFormation, loadFormation, resumeFormation, cancelCreation, type Book, type ContentOperation, type Formation } from "./api";

type Direction = {asset_version_id: string; content_hash: string; state: {lifecycle: string}; content?: {candidate_payload: Record<string,string>}};
type Pending = {kind: "book" | "brief" | "formation" | "direction" | "direction-decision" | "cancel" | "recover"; path?: string; body: Record<string, unknown>; workspaceBody?: Record<string, unknown>};
type Saved = {rejectedSubmissions?: Array<{request: Pending; reason: string}>; creativeSelection?: "AUTHOR_COMPARISON" | "AUTO_COMPARISON"; continuous?: boolean; language?: string; lengthMinimum?: number; lengthMaximum?: number;title: string; idea: string; genre: string; audience: string; constraints: string; sources: string; target: number; candidates: number; operationId: string; formationId: string; pending: Pending | null; directionOnly?: boolean; design?: Record<string,string>; direction?: Direction; directionReason?: string; contribution?: string; editorialEnabled?: boolean; editorial?: EditorialLearning; submittedBrief?: string};
const designFields = [["objective","故事目标"],["target_reader","目标读者"],["why_worth_writing","为什么值得写"],["genre","类型"],["subgenre","细分类型"],["core_desire","核心欲望"],["core_fear","核心恐惧"],["core_conflict","核心冲突与代价"],["narrative_engine","持续推动故事的机制"],["differentiation","与同类作品的差异"],["emotional_contract","阅读与情感承诺"],["serialization_potential","后继叙事空间"]];
const initial: Saved = {continuous: true, creativeSelection: "AUTO_COMPARISON", language: "zh-CN", lengthMinimum: 1200, lengthMaximum: 2400,title: "", idea: "", genre: "", audience: "", constraints: "", sources: "", target: 1, candidates: 2, operationId: "", formationId: "", pending: null};
const creationLabels: Record<string,string> = {MANUSCRIPT_READY:"当前范围稿件已交付，可阅读、修改和导出",PRODUCING:"正在创作",INTERNAL_ACCEPTANCE_COMPLETE:"正文已内部接纳，尚需选择正式版本并导出",CANCELLATION_REQUESTED:"取消已保存，正在处理",CANCELLED:"已取消",TECHNICAL_WAIT:"技术等待，系统自动恢复",RECONCILIATION_REQUIRED:"等待原请求结果对账",AUTHOR_DECISION:"等待作者方向决定",OWNER_RECOVERY_REQUIRED:"等待责任方解决停点",FINAL_FAILURE:"已终止失败",BOOK_AUTHORITY_WORKER:"作品生产执行器",RUNTIME_OWNER:"生产运行责任方",AUTHOR:"作者",WAIT_FOR_NATIVE_EXECUTOR:"等待执行器自动推进",RECOVER_ORIGINAL_CREATION_AFTER_RESOLVING_RETAINED_FAILURE:"先解决已保存问题，再恢复原任务",SELECT_EXACT_EDITION_AND_EXPORT:"选择正式版本并导出"};
export function CreativeInputPanel({project, book, release, formationId, onBook, onRefresh}: {formationId?: string;project?: ProjectRow; book?: Book; release?: string; onBook: (id: string) => void; onRefresh: () => Promise<void>}) {
  const key = `novel-forge:creative-input:${project?.project_id || ""}:${book?.book_id || "new"}`;
  const [saved, setSaved] = useState<Saved>(initial);
  const [ready, setReady] = useState(false);
  const [operation, setOperation] = useState<ContentOperation | null>(null);
  const [formation, setFormation] = useState<Formation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cards, setCards] = useState<EditorialCard[]>([]);
  const [knowledgeError, setKnowledgeError] = useState("");
  const lock = useRef(false);
  useEffect(() => {
    try { setSaved({...initial, ...JSON.parse(localStorage.getItem(key) || "{}")}); }
    catch { setError("本机创作输入读取失败，请保留原记录后重新输入。"); }
    setReady(true);
  }, [key]);
  useEffect(() => { if (ready) {try {localStorage.setItem(key, JSON.stringify(saved));} catch {setError("未能保存本机输入，请复制文字后恢复浏览器存储。原提交仍需核对。");}} }, [key, ready, saved]);
  useEffect(() => {
    let active = true;
    setCards([]); setKnowledgeError("");
    if (project && saved.editorialEnabled) fetchJson<EditorialCard[]>(`/product/mkaos/knowledge-cards?project_id=${encodeURIComponent(project.project_id)}&status=ACTIVE&limit=200`).then(rows => {if (active) setCards(eligibleEditorialCards(rows, project.project_id));}).catch(e => {if (active) setKnowledgeError(String(e));});
    return () => {active = false;};
  }, [project?.project_id, saved.editorialEnabled]);
  useEffect(() => {
    if (!project || !saved.operationId) {setOperation(null); return;}
    let active = true;
    const refresh = () => loadCreativeInput(project.project_id, saved.operationId).then(value => {if (active) setOperation(value);}).catch(e => {if (active) setError(String(e));});
    refresh(); const timer = setInterval(refresh, 5000);
    return () => {active = false; clearInterval(timer);};
  }, [project?.project_id, saved.operationId]);
  useEffect(() => {
    if (ready && formationId && !saved.formationId) retain({...saved, formationId});
  }, [ready, formationId, saved.formationId]);
  useEffect(() => {
    if (!saved.formationId) {setFormation(null); return;}
    let active = true;
    const refresh = () => loadFormation(saved.formationId).then(value => {if (active) setFormation(value);}).catch(e => {if (active) setError(String(e));});
    refresh(); const timer = setInterval(refresh, 5000);
    return () => {active = false; clearInterval(timer);};
  }, [saved.formationId]);
  function retain(value: Saved) {try {localStorage.setItem(key, JSON.stringify(value)); setSaved(value); return true;} catch {setError("输入未能保存，请先复制并恢复浏览器存储。"); return false;} }
  async function send(request: Pending) {
    if (lock.current || !project) return;
    lock.current = true; setBusy(true); setError("");
    const frozen = {...saved, pending: request}; if (!retain(frozen)) {lock.current = false; setBusy(false); return;}
    try {
      if (request.kind === "book") {
        if (request.workspaceBody) await createAuthorWorkspace(project.project_id, request.workspaceBody);
        await createAuthorBook(request.body);
        retain({...frozen, pending: null}); await onRefresh(); onBook(String(request.body.book_id));
      } else if (request.kind === "brief") {
        const result = await saveCreativeInput(request.body);
        retain({...frozen, pending: null, operationId: result.operation_id, submittedBrief: JSON.stringify(request.body.payload)});
      } else if(request.kind === "direction" || request.kind === "direction-decision") {
        const direction = await fetchJson<Direction>(request.path!, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(request.body)});
        retain({...frozen,pending:null,direction:{...direction,content:direction.content || frozen.direction?.content}});
      } else if (request.kind === "recover" && formation) {
        setFormation(await resumeFormation(formation,request.body)); retain({...frozen,pending:null});
      } else if (request.kind === "cancel" && formation) {
        setFormation(await cancelCreation(formation, request.body)); retain({...frozen,pending:null});
      } else {
        const result = await startFormation(String(request.body.book_id), request.body);
        retain({...frozen, pending: null, formationId: result.formation_run_id});
      }
    } catch(e) {
      if (e instanceof ApiError && e.status === 422) {
        retain({...frozen,pending:null,rejectedSubmissions:[...(frozen.rejectedSubmissions || []),{request,reason:String(e)}]});
        setError(`提交未通过输入校验，原请求已保留。请修正输入后再提交：${String(e)}`);
      } else setError(String(e));
    }
    finally {lock.current = false; setBusy(false);}
  }
  async function create() {
    if (!project || !release || lock.current) return;
    setBusy(true); setError("");
    try {
      const current = (await loadProductionProjects()).find(p => p.project_id === project.project_id);
      if (!current?.version || !current.asset_version_id) throw new Error("项目身份已变化，请重新选择。");
      const id = crypto.randomUUID();
      await send({kind: "book", workspaceBody: {workspace_id: `workspace:${id}`, expected_project_version: current.version, expected_project_asset_version_id: current.asset_version_id, idempotency_key: `workspace:${id}`},
        body: {project_id: project.project_id, workspace_id: `workspace:${id}`, book_id: `book:${id}`, title: saved.title, service_identity: "book-design-authority", production_profile: {}, runtime_policy: {execution_fallback: "FAIL_CLOSED"}, release_identity: release, idempotency_key: id, trace_id: `trace:${id}`, correlation_id: id}});
    } catch(e) {setError(String(e));} finally {setBusy(false);}
  }
  function brief() {
    if (!project || !book) return;
    if (saved.editorialEnabled && (learningProblems.length || knowledgeError)) return;
    void send({kind: "brief", body: {project_id: project.project_id, workspace_id: book.workspace_id, definition_name: "creative.brief.create", idempotency_key: crypto.randomUUID(), input_asset_version_ids: briefExtension.input_asset_version_ids, payload: briefPayload}});
  }
  function form() {
    const asset = operation?.outputs[0]; if (!asset || !book || !project) return;
    if (!briefMatches) return;
    if(saved.directionOnly && (saved.direction?.state.lifecycle!=="ACTIVE" || !directionMatches)) return;
    void send({kind: "formation", body: {project_id: project.project_id, workspace_id: book.workspace_id, book_id: book.book_id, expected_book_version: book.version, idempotency_key: crypto.randomUUID(), creative_brief_asset_version_id: asset.asset_version_id, creative_brief_content_hash: asset.content_hash, ...(saved.continuous ? {production_intent: {creative_selection: saved.creativeSelection || "AUTO_COMPARISON", title: saved.title || book.title, target_chapters: saved.target, creative_candidates: saved.candidates, language_contract: {required_language: saved.language}, chapter_length: {minimum: saved.lengthMinimum, maximum: saved.lengthMaximum}, ...(saved.directionOnly ? {author_creative_foundation:{asset_version_id:saved.direction!.asset_version_id,content_hash:saved.direction!.content_hash}} : {})}} : {generation_policy: {contract_version: saved.directionOnly ? "formation-generation.v3" : "formation-generation.v2", approval_mode: "REVIEW_PLAN", creative_candidates: saved.directionOnly ? 1 : saved.candidates, target_chapters: saved.target, title: saved.title || book.title, ...(saved.directionOnly ? {author_creative_foundation:{asset_version_id:saved.direction!.asset_version_id,content_hash:saved.direction!.content_hash}} : {})}})}});
  }
  const disabled = busy || !!saved.pending;
  const learning = saved.editorialEnabled ? saved.editorial : undefined;
  const learningProblems = saved.editorialEnabled ? learning && project && book ? editorialProblems(learning, cards, project.project_id, book.book_id) : ["请保存编辑讨论记录。"] : [];
  const briefExtension = editorialBriefExtension(learning);
  const {input_asset_version_ids: _inputs, ...extension} = briefExtension;
  const lines = (text: string) => text.split("\n").map(s => s.trim()).filter(Boolean);
  const briefPayload = {input_selection: {contract_version: "creative-input-selection.v1", book_id: book?.book_id || "", source_kind: "CURRENT_AUTHOR_INPUT", purpose: "WORK_PRODUCTION", intent_ref: `author-input:${book?.book_id || ""}`}, brief: {...extension, idea: saved.idea, genre: saved.genre, audience: saved.audience, constraints: lines(saved.constraints), source_boundaries: lines(saved.sources)}};
  const briefMatches = !saved.submittedBrief && !saved.editorialEnabled || saved.submittedBrief === JSON.stringify(briefPayload);
  const directionMatches = designFields.every(([name])=>saved.design?.[name]===saved.direction?.content?.candidate_payload[name]);
  const change = (field: keyof Saved, value: string | number) => setSaved(current => ({...current, [field]: value}));
  return <section className="panel">
    <h2>{book ? "创作输入与设计准备" : "登记新作品"}</h2>
    <p>已批准的作品可直接选择配置并解析快照。仅在缺少设计时启动设计准备；该操作可能产生模型调用，仍受现有授权、资格和预算约束。</p>
    <div className="formGrid wide">
      <label>作品标题<input aria-label="作品标题" value={saved.title} disabled={disabled} onChange={e => change("title", e.target.value)} placeholder={book?.title || "填写新作品标题"} /></label>
      {!book && <button disabled={disabled || !saved.title.trim() || !project?.workspace_id || !release} onClick={create}>登记作品</button>}
    </div>
    {book && <>
      <label>创作想法<textarea aria-label="创作想法" rows={5} value={saved.idea} disabled={disabled} onChange={e => change("idea", e.target.value)} /></label>
      <div className="formGrid wide">
        <label>类型<input aria-label="类型" value={saved.genre} disabled={disabled} onChange={e => change("genre", e.target.value)} /></label>
        <label>目标读者<input aria-label="目标读者" value={saved.audience} disabled={disabled} onChange={e => change("audience", e.target.value)} /></label>
        <label>创作约束（每行一条）<textarea aria-label="创作约束" value={saved.constraints} disabled={disabled} onChange={e => change("constraints", e.target.value)} /></label>
        <label>素材使用边界（每行一条）<textarea aria-label="素材使用边界" value={saved.sources} disabled={disabled} onChange={e => change("sources", e.target.value)} /></label>
      </div>
      <label><input type="checkbox" checked={!!saved.editorialEnabled} disabled={disabled || !!saved.formationId} onChange={e => retain({...saved, editorialEnabled: e.target.checked, editorial: saved.editorial || {contract_version: "editorial-learning.v1", book_id: book.book_id, version: crypto.randomUUID(), evidence_class: "OPERATOR_AUTHORED_INPUT", reader_promise: "", decisions: []}})}/>将参考讨论与专业依据带入原创设计</label>
      {learning && <EditorialLearningInput value={learning} cards={cards} disabled={disabled || !!saved.formationId} problems={learningProblems} onChange={value => retain({...saved, editorial: {...value, version: crypto.randomUUID()}})}/>}
      {knowledgeError && <p role="alert">知识目录读取失败：{knowledgeError}</p>}
      <button disabled={disabled || !saved.idea.trim() || !saved.genre.trim() || !saved.audience.trim() || !saved.constraints.trim() || !saved.sources.trim() || learningProblems.length > 0 || !!saved.editorialEnabled && !!knowledgeError} onClick={brief}>保存创作输入</button>
      {operation && <p>输入任务：{operation.status} · {operation.operation_id} · {operation.outputs[0]?.content_hash || "等待形成持久输入"}</p>}
      {operation && !briefMatches && <p>讨论或创作输入已修改，请先保存新版本；已提交版本保留。</p>}
      {saved.continuous && !saved.directionOnly && <label>方向选择<select aria-label="方向选择" value={saved.creativeSelection || "AUTO_COMPARISON"} disabled={disabled || !!saved.formationId} onChange={e=>retain({...saved,creativeSelection:e.target.value as Saved["creativeSelection"]})}><option value="AUTHOR_COMPARISON">生成后由我选择</option><option value="AUTO_COMPARISON">授权系统比较后继续（保留不确定性）</option></select></label>}
      <label><input type="checkbox" checked={!!saved.directionOnly} disabled={disabled || !!saved.formationId} onChange={e=>retain({...saved,directionOnly:e.target.checked})}/>使用我已确定的原创方向，直接进入下层设计</label>
      {saved.directionOnly && <fieldset><legend>确认原创方向</legend><p>先在监督面板选择本作品的作者监督模式。本输入走原生作者资产和审批流程；诊断候选保留原用途，不导入或改为正式资产。无需重新生成创意候选。</p>
        <div className="formGrid wide">{designFields.map(([name,label])=><label key={name}>{label}<textarea aria-label={label} value={saved.design?.[name] || ""} disabled={disabled} onChange={e=>retain({...saved,design:{...saved.design,[name]:e.target.value}})}/></label>)}</div>
        <label>内容贡献<select aria-label="内容贡献" value={saved.contribution || ""} disabled={disabled} onChange={e=>retain({...saved,contribution:e.target.value})}><option value="">如实选择来源</option><option value="OPERATOR_AUTHORED_INPUT">作者原创输入</option><option value="AI_ASSISTED_AUTHOR_INPUT">AI 协助整理，作者确认的原创输入</option></select></label>
        <button disabled={disabled || operation?.status!=="SUCCEEDED" || !saved.contribution || designFields.some(([name])=>!saved.design?.[name]?.trim())} onClick={()=>{const asset=operation?.outputs[0];if(!asset || !project) return;void send({kind:"direction",path:`/product/production/book-authority/books/${encodeURIComponent(book.book_id)}/author-creative-input`,body:{project_id:project.project_id,brief_asset_version_id:asset.asset_version_id,brief_content_hash:asset.content_hash,design:saved.design,contribution:saved.contribution,idempotency_key:crypto.randomUUID()}});}}>保存方向为待批准输入</button>
        {saved.direction && <><p>方向版本：{saved.direction.content_hash} · {saved.direction.state.lifecycle}</p><label>确认依据与保留的阅读承诺<textarea value={saved.directionReason || ""} disabled={disabled} onChange={e=>retain({...saved,directionReason:e.target.value})}/></label>
          {!directionMatches && <p>方向有未保存修改，请先保存新版本；原批准版本保持不变。</p>}
          <button disabled={disabled || !directionMatches || !saved.directionReason?.trim() || saved.direction.state.lifecycle==="ACTIVE"} onClick={()=>send({kind:"direction-decision",path:`/product/production/book-authority/books/${encodeURIComponent(book.book_id)}/author-creative-input/${encodeURIComponent(saved.direction!.asset_version_id)}/decisions`,body:{project_id:project!.project_id,content_hash:saved.direction!.content_hash,reason:saved.directionReason,decision:"APPROVE",findings:[],idempotency_key:crypto.randomUUID()}})}>批准此版本并选择为创作方向</button></>}
      </fieldset>}
      {<label><input type="checkbox" checked={!!saved.continuous} disabled={disabled || !!saved.formationId} onChange={e => retain({...saved, continuous: e.target.checked})}/>{saved.directionOnly ? "采用已批准原创方向后连续生产" : "比较方向后连续生产"}；技术等待由任务自动恢复</label>}
      {saved.continuous && <div className="formGrid wide">
        <label>正文语言<input aria-label="正文语言" value={saved.language || ""} disabled={disabled} onChange={e => retain({...saved,language:e.target.value})}/></label>
        <label>每章最少字数<input type="number" min={1} value={saved.lengthMinimum} disabled={disabled} onChange={e => retain({...saved,lengthMinimum:Number(e.target.value)})}/></label>
        <label>每章最多字数<input type="number" min={saved.lengthMinimum} value={saved.lengthMaximum} disabled={disabled} onChange={e => retain({...saved,lengthMaximum:Number(e.target.value)})}/></label>
      </div>}
      <div className="formGrid wide">
        <label>设计目标章数<input aria-label="设计目标章数" type="number" min={1} max={10000} value={saved.target} disabled={disabled} onChange={e => change("target", Number(e.target.value))} /></label>
        {!saved.directionOnly && <label>比较候选数<select aria-label="比较候选数" value={saved.candidates} disabled={disabled} onChange={e => change("candidates", Number(e.target.value))}>{[2,3,4].map(n => <option key={n}>{n}</option>)}</select></label>}
        <button disabled={disabled || !briefMatches || operation?.status !== "SUCCEEDED" || !operation.outputs.length || !!saved.formationId || saved.target < 1 || saved.target > 10000 || !!saved.continuous && (!saved.language?.trim() || !Number.isInteger(saved.lengthMinimum) || !Number.isInteger(saved.lengthMaximum) || (saved.lengthMinimum || 0) < 1 || (saved.lengthMaximum || 0) < (saved.lengthMinimum || 0) || (saved.lengthMaximum || 0) > 100000) || !!saved.directionOnly && (saved.direction?.state.lifecycle!=="ACTIVE" || !directionMatches)} onClick={form}>{saved.continuous ? saved.directionOnly ? "以已批准方向启动连续创作" : "开始写作" : "启动设计准备（确认计划后推进）"}</button>
      </div>
      {formation?.creation?.production?.book_run_id && project && <CurrentManuscriptPanel project={project.project_id} bookRun={formation.creation.production.book_run_id} />}
      {formation && <div><FormationReviewPanel formation={formation} onChange={setFormation} />
        {["PLANNING_RESULT_REPAIR_BOUND_EXCEEDED", "PLANNING_REPAIR_BOUND_EXCEEDED"].includes(formation.creation?.failure?.code || "") && <p role="alert">方案修复次数已用完。请根据诊断决定未来方案，或补充已批准的初始信息；再次恢复不会增加次数。</p>}
        {formation.creation ? <div><p role="status">创作进度：{creationLabels[formation.creation.coordination?.result?.wait_class || formation.creation.author_state] || creationLabels[formation.creation.author_state] || "等待执行器接管"}。{formation.creation.production && <>已保存 {formation.creation.production.saved_chapters}/{formation.creation.production.target_chapters} 章，审定至 {formation.creation.production.accepted_chapters} 章。</>} {formation.creation.responsible_party && <>当前责任方：{creationLabels[formation.creation.responsible_party] || "原阶段责任方"}。</>} {formation.creation.next_action && <>下一动作：{creationLabels[formation.creation.next_action] || "按已保存停点处理"}。</>}</p><p>正文可在阅读与编辑入口查看；内部接纳、正式版本导出和文学质量分别核验。</p></div> : <p>设计状态：{formation.lifecycle} · {formation.current_stage}</p>}
        <details><summary>执行停点与来源诊断</summary><pre>{JSON.stringify({design_state:formation.lifecycle,stage:formation.current_stage,failure:formation.failure,recovery:formation.recovery_instruction,coordination:formation.creation?.coordination,next_action:formation.creation?.next_action,responsible_party:formation.creation?.responsible_party},null,2)}</pre></details>
        <button disabled={disabled || !!formation.creation?.cancellation || !["FAILED", "WAITING_APPROVAL"].includes(formation.lifecycle) && !["OWNER_RECOVERY_REQUIRED","RECONCILIATION_REQUIRED"].includes(formation.creation?.coordination?.result?.wait_class || "")} onClick={() => send({kind:"recover",body:{expected_version:formation.version,...(formation.creation ? {reason:"作者核对持久停点后请求原身份恢复",idempotency_key:crypto.randomUUID()} : {})}})}>核对停点后恢复创作</button>
        {formation.creation && <button className="dangerButton" disabled={disabled || !!formation.creation.cancellation || formation.creation.coordination?.result?.wait_class === "COMPLETED"} onClick={() => send({kind:"cancel",body:{expected_version:formation.version,reason:"作者取消连续创作",idempotency_key:crypto.randomUUID()}})}>取消连续创作</button>}
        {formation.book_design_asset_version_id && <a href={`/assets?path=${encodeURIComponent(`authority://asset-version/${formation.book_design_asset_version_id}`)}`}>查看设计版本与依据</a>}
      </div>}
    </>}
    {saved.pending && <button disabled={busy} onClick={() => send(saved.pending!)}>恢复上次提交（保留原输入和幂等键）</button>}
    {error && <p role="alert" className="errorLine">{error}</p>}
  </section>;
}
