"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, fetchJson } from "../../shared/api";
import { describe } from "./FormationReviewPanel";
import type { Book } from "./api";

type Candidate = {candidate: {candidate_id: string; model: string; model_revision: string; provider: string; pricing: {currency: string; accounting_basis: string}}; rejected_reasons: string[]; estimated_total_tokens: number; reservation_upper_bound: string | null};
type Producer = {routing_asset_version_id: string; task_type: string; producer_contract_hash: string; status: string; candidates: Candidate[]; budget?: Record<string, unknown>; operation_id?: string; review_requirement?: {schema_version: string; target_asset_version_id: string; target_content_hash: string; reviewer_policy?: string; required_reviewer_provider?: string; source?: {kind: string}; authorized_reviewer?: {provider?: string; model_revision?: string}}};
type Controls = {book_control: {scope: string; selected_policy: {mode: string; policy_version: string} | null; selected_boundaries: string[]; supervised_boundaries: string[]}; dispatch: {state: string; api_process_suspended: boolean}; budget_ledger: {scope: string; rows: Array<{provider: string; currency: string; status: string; accounting_basis: string; cost_status: string; reservations: number; actual_tokens: number; estimated_tokens: number; reserved_amount: string | null; settled_amount: string | null}>}};
type Design = {asset_version_id: string; content_hash: string; content: Record<string, unknown>; qualification: string; approval: string; planning_scope: string};
type Finding = {criterion: string; verdict: string; rationale: string; evidence_refs: string[]; repair_directive: string};
type Review = {asset_version_id: string; content_hash: string; content: {candidate_asset_version_id: string; candidate_content_hash: string; evaluation: {evaluations: Array<{layer: string; criteria: Finding[]}>}; provider_execution: {provider_id: string; model_id: string}}};
type View = {controls?: Controls; book_modes: Array<{book_id: string; reason: string}>; policy_hash: string; policy_version: string; authorizations: Array<{task_type: string; model_revision: string; expires_at: string; maximum_tokens: number; maximum_amount: string; expired?: boolean}>; producers: Producer[]; pending_designs: Design[]; model_reviews: Review[]};
type Saved = {route: string; model: string; expires: string; tokens: number; amount: string; reason: string; dispositions?: Record<string, {disposition: string; reason: string}>; rejected?: Array<{path: string; body: Record<string, unknown>; code: string}>; pending: {path: string; body: Record<string, unknown>} | null};
const initial: Saved = {route:"",model:"",expires:"",tokens:100000,amount:"0",reason:"",pending:null};
export function AuthorSupervisionPanel({project, book}: {project: string; book: Book}) {
  const prefix = `/product/production/book-authority/books/${encodeURIComponent(book.book_id)}`;
  const storageKey = `novel-forge:author-supervision:${project}:${book.book_id}`;
  const [view,setView] = useState<View | null>(null), [saved,setSaved] = useState<Saved>(initial), [busy,setBusy] = useState(false), [error,setError] = useState("");
  const lock = useRef(false);
  const refresh = () => fetchJson<View>(`${prefix}/author-supervision?${new URLSearchParams({project_id:project})}`).then(setView);
  useEffect(() => {try {setSaved(JSON.parse(localStorage.getItem(storageKey) || "null") || initial);} catch {setError("监督决定草稿读取失败，请保留原记录。");} void refresh().catch(e=>setError(String(e)));}, [storageKey]);
  function retain(value: Saved) {try {localStorage.setItem(storageKey,JSON.stringify(value));setSaved(value);return true;} catch {setError("无法保存原请求，请先恢复本机存储。");return false;}}
  async function send(pending: NonNullable<Saved["pending"]>) {
    if (lock.current || !retain({...saved,pending})) return;
    lock.current=true;setBusy(true);setError("");
    try {await fetchJson(pending.path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(pending.body)});retain({...saved,pending:null});await refresh();}
    catch(e) {
      if(e instanceof ApiError && e.code === "ROUTING_POLICY_VERSION_CONFLICT") {
        retain({...saved,pending:null,rejected:[...(saved.rejected || []),{...pending,code:e.code}]});
        setError("配置已有更新，此次决定被拒绝且已保留记录。请查询当前配置，核对后重新确认。");
        await refresh().catch(()=>setError("此次决定被拒绝且已保留记录；当前配置查询失败，请重试查询。"));
      } else setError(String(e));
    } finally {lock.current=false;setBusy(false);}
  }
  const producer=view?.producers.find(p=>p.routing_asset_version_id===saved.route);
  const model=producer?.candidates.find(c=>c.candidate.candidate_id===saved.model);
  const disabled=busy || !!saved.pending;
  function grant() {if(!view || !producer || !model) return;void send({path:`${prefix}/author-supervision`,body:{project_id:project,routing_asset_version_id:saved.route,candidate_id:saved.model,expires_at:new Date(saved.expires).toISOString(),maximum_tokens:saved.tokens,maximum_amount:saved.amount,reason:saved.reason,expected_policy_hash:view.policy_hash,idempotency_key:crypto.randomUUID()}});}
  function findings(design: Design) {return (view?.model_reviews || []).filter(r=>r.content.candidate_asset_version_id===design.asset_version_id && r.content.candidate_content_hash===design.content_hash).flatMap(r=>r.content.evaluation.evaluations.flatMap(p=>p.criteria.filter(f=>f.verdict!=="PASS").map(f=>({...f,id:`${r.asset_version_id}:${p.layer}:${f.criterion}`}))));}
  function decide(design: Design, decision: string) {void send({path:`${prefix}/planning-candidates/${encodeURIComponent(design.asset_version_id)}/author-decisions`,body:{project_id:project,content_hash:design.content_hash,reason:saved.reason,decision,findings:findings(design).map(f=>({finding_id:f.id,...saved.dispositions?.[f.id]})),idempotency_key:crypto.randomUUID()}});}
  return <section className="panel"><h2>作者监督试生产</h2>
    <p>仅批准本作品的指定任务、Producer 和模型。独立文学资格仍未证明；计划、正文终稿和事实接纳需要作者判断。结构、引用、预算、权限和 UNKNOWN 对账继续生效。</p>
    <p>这项决定不会追加预算、续期原额度或释放历史暂停。模型文学资格不足可由作者监督处理；明确的结构或事实错误必须修复。</p>
    <p>模型直接生成稿绑定真实生成回执，由另一 Provider 审读。作者稿、模型后人工修改稿及 edition 混合稿绑定当前稿件版本、hash 与原生来源，使用明确授权的审读模型，无需虚构新稿生成回执。语义设计建议与 Canon support 按各自目标合同校验。模型复核仍是作者判断的依据，独立文学资格未证明。</p>
    <h3>1. 本作品的设计模式</h3><p>本作品新设计模式：{view ? (view.book_modes.length ? "作者监督试生产" : "严格资格") : "正在查询"}。旧冻结输入保持原模式。</p>
    <button disabled={disabled} onClick={()=>refresh().catch(e=>setError(String(e)))}>查询任务与原审批</button>
    <h3>2. 任务授权、预算与派发</h3>
    {view?.controls && <><p>项目派发状态：{view.controls.dispatch.state}；当前 API 进程禁止新模型派发：{view.controls.dispatch.api_process_suspended ? "是" : "否"}。这不是 worker 状态或任务可执行性证明；解除暂停需使用原运行控制入口。</p>
      <details><summary>项目累计预算账本（含其他作品与历史记录）</summary>
        <p>以下是当前账本原始分组，授权上限不是累计余额。RESERVED / HELD_UNKNOWN 保留占用；订阅权益与未知费用不计为零成本。实际 tokens 与估算 tokens 分列，不相加。</p>
        {!view.controls.budget_ledger.rows.length && <p>项目尚无预算预约记录；不据此认定已授权。</p>}
        {view.controls.budget_ledger.rows.map((r,i)=><p key={i}>{r.provider} · {r.status} · {r.accounting_basis} · 费用状态 {r.cost_status} · {r.reservations} 条预约 · 已记录实际 tokens {r.actual_tokens} · 原估算 tokens {r.estimated_tokens} · 预约金额 {r.reserved_amount ?? "未知"} · 结算金额 {r.settled_amount ?? "未知"} {r.currency}</p>)}
      </details></>}
    {view?.authorizations.map((g,i)=><p key={i}>授权记录（{g.expired ? "已过期，需作者重新确认" : "有效期内，派发仍需检查"}）：{g.task_type} · {g.model_revision} · 截止 {g.expires_at} · 单次 tokens ≤ {g.maximum_tokens} · 金额 ≤ {g.maximum_amount}（路由计价币种）</p>)}
    {!view?.producers.length && <p>尚无本作品可批准的实际任务合同。先保存作者输入并准备原生任务；诊断候选不列为生产输入。</p>}
    {!!view?.producers.length && <div className="formGrid wide">
      <label>实际任务<select aria-label="实际任务" value={saved.route} disabled={disabled} onChange={e=>retain({...saved,route:e.target.value,model:""})}><option value="">选择已准备的任务</option>{view.producers.map(p=><option key={p.routing_asset_version_id} value={p.routing_asset_version_id}>{p.task_type} · {p.status} · {p.producer_contract_hash.slice(-10)}{p.review_requirement ? ` · ${p.review_requirement.target_asset_version_id}` : ""}</option>)}</select></label>
      <label>限定模型<select aria-label="限定模型" value={saved.model} disabled={disabled || !producer} onChange={e=>retain({...saved,model:e.target.value})}><option value="">选择模型</option>{producer?.candidates.map(c=><option key={c.candidate.candidate_id} value={c.candidate.candidate_id}>{c.candidate.provider} · {c.candidate.model_revision}</option>)}</select></label>
      {producer && <><p>任务合同：{producer.producer_contract_hash}；Operation：{producer.operation_id || "未记录"}。</p>
        {producer.review_requirement && <p>当前审读目标：{producer.review_requirement.target_asset_version_id} · {producer.review_requirement.target_content_hash}；来源：{producer.review_requirement.source?.kind || "直接模型生成"}；审读要求：{producer.review_requirement.reviewer_policy || "另一 Provider"} · {producer.review_requirement.required_reviewer_provider || producer.review_requirement.authorized_reviewer?.provider || "需选择并授权模型"}。</p>}
        <details><summary>此路由冻结时的预算快照（非实时余额）</summary><p>{describe(producer.budget || {})}</p></details></>}
      {model && <p>当前拒绝原因：{model.rejected_reasons.join("、") || "无"}。预计 tokens：{model.estimated_total_tokens}；预约金额：{model.reservation_upper_bound ?? "订阅权益，不等于零成本"} {model.candidate.pricing.currency}。</p>}
      <label>截止时间<input type="datetime-local" value={saved.expires} disabled={disabled} onChange={e=>retain({...saved,expires:e.target.value})}/></label>
      <label>单次 tokens 上限<input type="number" min={1} value={saved.tokens} disabled={disabled} onChange={e=>retain({...saved,tokens:Number(e.target.value)})}/></label>
      <label>单次金额上限（{model?.candidate.pricing.currency || "路由币种"}）<input inputMode="decimal" value={saved.amount} disabled={disabled} onChange={e=>retain({...saved,amount:e.target.value})}/></label>
    </div>}
    <label>批准理由 / 保留优点 / 修改意见<textarea value={saved.reason} disabled={disabled} onChange={e=>retain({...saved,reason:e.target.value})}/></label>
    <div className="actions">{(["AUTHOR_SUPERVISED","STRICT"] as const).map(mode=><button key={mode} disabled={disabled || !view || !saved.reason.trim()} onClick={()=>send({path:`${prefix}/author-supervision/mode`,body:{project_id:project,mode,reason:saved.reason,expected_policy_hash:view!.policy_hash,idempotency_key:crypto.randomUUID()}})}>{mode === "AUTHOR_SUPERVISED" ? "确认本作品采用作者监督模式" : "本作品的新请求恢复严格资格模式"}</button>)}</div>
    {!!producer && <button disabled={disabled || !model || !saved.expires || !saved.reason.trim() || saved.tokens<1 || !/^\d+(\.\d+)?$/.test(saved.amount)} onClick={grant}>确认限定范围并批准试生产</button>}
    <h3>3. Book Control 作者确认边界</h3>
    {view?.controls ? <><p>项目级新请求策略：{view.controls.book_control.selected_policy ? `${view.controls.book_control.selected_policy.mode} · ${view.controls.book_control.selected_policy.policy_version}` : "尚未显式选择"}。项目级调整影响该项目其他 Book 的新请求；本作品设计模式按钮只修改本 Book。</p>
      {view.controls.book_control.selected_policy && <p>已选策略确认边界：{view.controls.book_control.selected_boundaries.join("、") || "无"}。</p>}
      <p>监督型设计在未配置项目策略时使用 AUTHOR_SUPERVISED 默认边界：{view.controls.book_control.supervised_boundaries.join("、")}。已选项目策略若不兼容，原生启动门禁会阻断。旧冻结请求继续使用原政策。</p>
      <p>等待作者判断是正常阶段：阅读下方精确计划与模型发现后提交决定，再从原任务恢复。正文终稿与事实接纳在生产链对应待处理事项中确认；批准启动不代表批准未来未知正文。</p></> : <p>尚未读取确认策略，不能推断确认边界。</p>}
    {!!view?.pending_designs.length && <h3>需要作者判断的精确计划</h3>}
    {view?.pending_designs.map(d=><article className="panel" key={d.asset_version_id}><h4>{d.planning_scope} · {d.qualification} · {d.approval}</h4>
      <dl>{Object.entries((d.content.candidate_payload || d.content) as Record<string,unknown>).filter(([k])=>!["execution_evidence","schema_version","frozen_inputs","constraint_envelope"].includes(k)).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{describe(v)}</dd></div>)}</dl>
      <p>{d.content_hash} · 独立文学资格未证明</p><details><summary>冻结约束与来源</summary><p>{describe(d.content.constraint_envelope)}</p><p>{describe(d.content.frozen_inputs)}</p></details>
      <button disabled={disabled || view.model_reviews?.some(r=>r.content.candidate_asset_version_id===d.asset_version_id && r.content.candidate_content_hash===d.content_hash)} onClick={()=>send({path:`${prefix}/planning-candidates/${encodeURIComponent(d.asset_version_id)}/model-reviews`,body:{project_id:project,content_hash:d.content_hash,idempotency_key:crypto.randomUUID()}})}>请求模型复核此精确版本</button>
      {view.model_reviews?.filter(r=>r.content.candidate_asset_version_id===d.asset_version_id && r.content.candidate_content_hash===d.content_hash).map(r=><aside key={r.asset_version_id}><h4>模型审读建议 · {r.content.provider_execution.provider_id} / {r.content.provider_execution.model_id}</h4><p>{describe(r.content.evaluation)}</p><p>审读版本 {r.content_hash} · 作者尚需判断争议，文学资格未证明。</p></aside>)}
      {findings(d).map(f=><fieldset key={f.id}><legend>{f.criterion} · {f.verdict}</legend><p>{f.rationale}</p><p>依据：{f.evidence_refs.join("；")}。建议：{f.repair_directive}</p>
        <label>作者判断<select aria-label={`作者判断：${f.criterion}`} value={saved.dispositions?.[f.id]?.disposition || ""} disabled={disabled} onChange={e=>retain({...saved,dispositions:{...saved.dispositions,[f.id]:{reason:saved.dispositions?.[f.id]?.reason || "",disposition:e.target.value}}})}><option value="">请选择处理方式</option><option value="DISMISSED_WITH_EVIDENCE">依据原文驳回此判断</option><option value="RESOLVED">已有证据证明问题解决</option></select></label>
        <label>原文依据与处理理由<textarea aria-label={`原文依据与处理理由：${f.criterion}`} value={saved.dispositions?.[f.id]?.reason || ""} disabled={disabled} onChange={e=>retain({...saved,dispositions:{...saved.dispositions,[f.id]:{disposition:saved.dispositions?.[f.id]?.disposition || "",reason:e.target.value}}})}/></label></fieldset>)}
      <button disabled={disabled || !saved.reason.trim() || findings(d).some(f=>!saved.dispositions?.[f.id]?.disposition || !saved.dispositions?.[f.id]?.reason.trim())} onClick={()=>decide(d,"APPROVE")}>批准并选择此计划</button>
      <button disabled={disabled || !saved.reason.trim()} onClick={()=>decide(d,"REQUEST_CHANGES")}>记录修改意见并拒绝当前候选</button>
    </article>)}
    {saved.pending && <button disabled={busy} onClick={()=>send(saved.pending!)}>恢复原监督决定（原幂等键）</button>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
