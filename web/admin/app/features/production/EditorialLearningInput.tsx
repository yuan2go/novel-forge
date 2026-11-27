"use client";

import type { EditorialLearning, EditorialDecision, EditorialCard } from "./editorial-learning";

const targets = [["CREATIVE_FOUNDATION", "创作方向"], ["WORLD_BIBLE", "世界规则"], ["CHARACTER_CAST", "人物关系"], ["BOOK", "全书规划"], ["ARC", "故事弧"], ["CHAPTER", "逐章规划"]];
const choices = [["KEEP", "保留优势"], ["ADAPT", "条件采用／修正坑点"], ["AVOID", "明确避免"], ["DEFER", "证据不足，暂缓"]];

export function EditorialLearningInput({value, cards, disabled, onChange, problems}: {value: EditorialLearning; cards: EditorialCard[]; disabled: boolean; onChange: (value: EditorialLearning) => void; problems: string[]}) {
  function update(index: number, patch: Partial<EditorialDecision>) {
    onChange({...value, decisions: value.decisions.map((item, position) => position === index ? {...item, ...patch} : item)});
  }
  return <fieldset aria-label="参考作品讨论后的编辑取舍"><legend>参考作品讨论后的编辑取舍</legend>
    <p>只填写抽象机制和作者取舍。采用专业依据时保留其条件与副作用，让知识改善事件和选择；不把原作原文或校核报告塞进正文。这些输入仍是待执行意图。</p>
    <label>希望保留的类型与阅读体验<textarea aria-label="希望保留的类型与阅读体验" value={value.reader_promise} disabled={disabled} onChange={e => onChange({...value, reader_promise: e.target.value})}/></label>
    <label>讨论记录来源<select value={value.evidence_class} disabled={disabled} onChange={e => onChange({...value, evidence_class: e.target.value as EditorialLearning["evidence_class"]})}><option value="OPERATOR_AUTHORED_INPUT">作者整理的取舍</option><option value="AI_ASSISTED_AUTHOR_INPUT">与 AI 讨论后由作者整理</option></select></label>
    {!cards.length && <p role="status">本项目尚无可用的已批准知识卡。请先在<a href="/mkaos/creative-assets">素材与知识入口</a>提炼、核验并批准抽象机制或专业依据；暂不能声称已经完成知识优化。</p>}
    {value.decisions.map((item, index) => <fieldset key={item.decision_id}><legend>取舍 {index + 1}</legend>
      <label>处理方式<select value={item.choice} disabled={disabled} onChange={e => update(index, {choice: e.target.value as EditorialDecision["choice"]})}>{choices.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <div className="formGrid wide">{[["finding", "优势／问题及证据判断"], ["application", "原创应用、修正方式与适用条件"], ["reader_effect", "预期改善的阅读体验"], ["tradeoff", "副作用与取舍"]].map(([field, label]) => <label key={field}>{label}<textarea value={item[field as "finding"]} disabled={disabled} onChange={e => update(index, {[field]: e.target.value})}/></label>)}</div>
      <div>{targets.map(([id, label]) => <label key={id}><input type="checkbox" checked={item.targets.includes(id)} disabled={disabled} onChange={e => update(index, {targets: e.target.checked ? [...item.targets, id] : item.targets.filter(target => target !== id)})}/>{label}</label>)}</div>
      <div className="formGrid"><label>适用起始章<input type="number" min={1} max={10000} value={item.chapter_range[0]} disabled={disabled} onChange={e => update(index, {chapter_range: [Number(e.target.value), item.chapter_range[1]]})}/></label><label>适用结束章<input type="number" min={1} max={10000} value={item.chapter_range[1]} disabled={disabled} onChange={e => update(index, {chapter_range: [item.chapter_range[0], Number(e.target.value)]})}/></label></div>
      <p>绑定已批准的抽象机制／专业依据（按实际设计阶段选择，最多六项）</p>
      {cards.map(card => {const selected = item.knowledge_cards.some(ref => ref.asset_version_id === card.asset_version_id && ref.content_hash === card.content_hash); const abstract = card.content.abstract_content; return <label key={card.asset_version_id}><input type="checkbox" checked={selected} disabled={disabled || !selected && item.knowledge_cards.length >= 6} onChange={e => update(index, {knowledge_cards: e.target.checked ? [...item.knowledge_cards.filter(ref => ref.asset_version_id !== card.asset_version_id), {asset_version_id: card.asset_version_id, content_hash: card.content_hash}] : item.knowledge_cards.filter(ref => ref.asset_version_id !== card.asset_version_id)})}/>{abstract?.concept_name || card.asset_version_id}<small> · {abstract?.mechanism} · 适用：{abstract?.applicability?.join("；")} · 失效：{abstract?.failure_conditions?.join("；")}</small></label>;})}
      <button disabled={disabled} onClick={() => onChange({...value, decisions: value.decisions.filter((_, position) => position !== index)})}>移除此项</button>
    </fieldset>)}
    <button disabled={disabled || value.decisions.length >= 12} onClick={() => onChange({...value, decisions: [...value.decisions, {decision_id: crypto.randomUUID(), choice: "ADAPT", finding: "", application: "", reader_effect: "", tradeoff: "", targets: ["CREATIVE_FOUNDATION", "BOOK"], chapter_range: [1, 100], knowledge_cards: []}]})}>增加编辑取舍</button>
    {problems.length > 0 && <ul>{problems.map(problem => <li key={problem}>{problem}</li>)}</ul>}
  </fieldset>;
}
