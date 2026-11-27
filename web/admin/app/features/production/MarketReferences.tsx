"use client";
import { useState } from "react";
import { fetchJson } from "../../shared/api";
import type { EditorialCard } from "./editorial-learning";

type Entry = {work_id: string; book_source_id: string; title: string; rank: number; url: string; author: string};
type Rank = {definition_id: string; status: string; unavailable_reason: string; definition: {official_name: string; category_label: string; period: string; support: string; metric_explanation: string; url: string}; entries: Entry[]; latest_attempt?: {status: string; observed_at: string}; last_valid_snapshot?: {observed_at: string; payload?: {requested_top_n: number}}};
type Work = {knowledge_cards: EditorialCard[]; unavailable_card_asset_version_ids?: string[]; editions: {edition_id: string; title: string; evidence_ref: string}[]; source_works: {source_work_asset_version_id: string; source_document_id: string}[]; rights_requirements: string};
const labels: Record<string,string> = {COMPLETE:"所需范围完整", PARTIAL:"部分获取", STALE:"数据已过期", NOT_OBSERVED:"尚无有效观测", REVOKED:"来源或用途已失效", CHALLENGE:"访问受验证限制", ACCESS_DENIED:"访问被拒绝", RATE_LIMITED:"站点限流", PARSE_DRIFT:"页面结构变化", UNVERIFIED:"入口未核实", UNSUPPORTED:"不支持"};

export function MarketReferences({projectId, disabled, onCard}: {projectId: string; disabled: boolean; onCard: (card: EditorialCard) => void}) {
  const [category,setCategory]=useState(""); const [ranks,setRanks]=useState<Rank[]>([]);
  const [next,setNext]=useState(""); const [busy,setBusy]=useState(false); const [error,setError]=useState("");
  const [work,setWork]=useState<Work|null>(null);
  const [evidence,setEvidence]=useState<unknown>(null);
  async function inspectEvidence(path: string) {
    setBusy(true);setError("");setEvidence(null);
    try {setEvidence(await fetchJson<unknown>(`${path}?project_id=${encodeURIComponent(projectId)}`));}
    catch(e){setError(String(e));} finally {setBusy(false);}
  }
  async function query(after="") {
    setBusy(true);setError("");
    try {const result=await fetchJson<{items:Rank[];next_after:string}>(`/product/source-governance/market/ranks?project_id=${encodeURIComponent(projectId)}&category=${category}&after=${encodeURIComponent(after)}`);setRanks(after?[...ranks,...result.items]:result.items);setNext(result.next_after);}
    catch(e){setError(String(e));} finally {setBusy(false);}
  }
  async function inspect(entry: Entry) {
    setBusy(true);setError("");setWork(null);setEvidence(null);
    try {setWork(await fetchJson<Work>(`/product/source-governance/market/works/${encodeURIComponent(entry.book_source_id)}?project_id=${encodeURIComponent(projectId)}`));}
    catch(e){setError(String(e));} finally {setBusy(false);}
  }
  return <details><summary>查找热门作品与叙事参考（可选）</summary>
    <p>榜单是市场观察。参考文本须有对应使用依据；已有机制卡按本书取舍采用，热度不代表机制有效。</p>
    <label>分类<select value={category} onChange={e=>{setCategory(e.target.value);setRanks([]);setNext("");setWork(null);}}><option value="">所有已登记口径</option>{[["ALL","全部"],["XUANHUAN","玄幻"],["WUXIA","武侠"],["XIANXIA","仙侠"]].map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
    <button type="button" disabled={busy} onClick={()=>void query()}>查榜</button>
    {error && <p role="alert">参考查询失败：{error}。仍可按当前原创输入继续。</p>}
    {!busy && !ranks.length && <p>尚未读取到有据可查的榜单。可在现有<a href="/mkaos/import">来源入口</a>导入授权快照或自有阅读笔记；未核实入口不会显示成实时榜单。</p>}
    {ranks.map(rank=><fieldset key={rank.definition_id}><legend>{rank.definition.official_name} · {rank.definition.category_label} · {rank.definition.period}</legend>
      <p>{labels[rank.status]||rank.status} · 入口：{labels[rank.definition.support]||rank.definition.support} · 数据观测：{rank.last_valid_snapshot?.observed_at||"无"} · 范围：{rank.last_valid_snapshot?.payload?.requested_top_n ? `Top ${rank.last_valid_snapshot.payload.requested_top_n}`:"未覆盖"} · 最近获取：{labels[rank.latest_attempt?.status||""]||rank.latest_attempt?.status||"无"}</p>
      <p>{rank.definition.metric_explanation} {rank.unavailable_reason}</p><a href={rank.definition.url} target="_blank" rel="noreferrer">官方榜单链接</a>
      {rank.entries.map(entry=><div key={entry.work_id}>{entry.rank} · <a href={entry.url} target="_blank" rel="noreferrer">{entry.title}</a> · {entry.author} <button type="button" disabled={busy} onClick={()=>void inspect(entry)}>查看来源与机制</button></div>)}
    </fieldset>)}
    {next && <button type="button" disabled={busy} onClick={()=>void query(next)}>下一页榜单口径</button>}
    {work && <fieldset><legend>来源、覆盖与可用机制</legend>
      {work.editions.map(edition=><p key={edition.edition_id}>{edition.title} · {edition.evidence_ref} · <button type="button" disabled={busy} onClick={()=>void inspectEvidence(`/product/source-governance/corpus/lineage/${encodeURIComponent(edition.edition_id)}`)}>查看来源权限与样本范围</button></p>)}
      <p>已登记文本处理版本：{work.source_works.length}。证据范围须在来源分析中核对。</p>
      {!work.knowledge_cards.length && <p>没有当前可用的已批准机制卡；不能依据榜名或简介补造文本分析。</p>}
      {!!work.unavailable_card_asset_version_ids?.length && <p role="status">已有参考版本当前不可用，请查看原版本证据和来源权限，再调整或撤销：{work.unavailable_card_asset_version_ids.join("、")}</p>}
      {work.knowledge_cards.map(card=><div key={card.asset_version_id}><p>{card.content.abstract_content?.concept_name} · {card.content.abstract_content?.mechanism}</p><p>适用：{card.content.abstract_content?.applicability?.join("；")} · 失效：{card.content.abstract_content?.failure_conditions?.join("；")}</p><button type="button" disabled={disabled} onClick={()=>onCard(card)}>列入本书编辑取舍</button> <button type="button" disabled={busy} onClick={()=>void inspectEvidence(`/product/mkaos/knowledge-cards/${encodeURIComponent(card.asset_version_id)}/trace`)}>查看机制及证据</button></div>)}
      {evidence !== null && <details open><summary>来源与证据记录</summary><pre>{JSON.stringify(evidence,null,2)}</pre></details>}
    </fieldset>}
  </details>;
}
