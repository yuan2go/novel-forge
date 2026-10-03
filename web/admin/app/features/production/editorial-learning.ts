export type KnowledgeRef = {asset_version_id: string; content_hash: string};
export type EditorialDecision = {
  decision_id: string; choice: "KEEP" | "ADAPT" | "AVOID" | "DEFER";
  finding: string; application: string; reader_effect: string; tradeoff: string;
  targets: string[]; chapter_range: [number, number]; knowledge_cards: KnowledgeRef[];
};
export type EditorialLearning = {
  contract_version: "editorial-learning.v1"; book_id: string; version: string;
  evidence_class: "OPERATOR_AUTHORED_INPUT" | "AI_ASSISTED_AUTHOR_INPUT";
  reader_promise: string; decisions: EditorialDecision[];
};
export type EditorialCard = KnowledgeRef & {project_id: string; lifecycle: string; eligibility: string; governance: string; card_status: string; content: {abstract_content?: {concept_name?: string; mechanism?: string; applicability?: string[]; failure_conditions?: string[]; semantic_family?: string}}};

export function eligibleEditorialCards(cards: EditorialCard[], projectId: string) {
  return cards.filter(card => card.project_id === projectId && card.lifecycle === "ACTIVE" && card.eligibility === "ELIGIBLE" && card.governance === "CLEAR" && card.card_status === "ACTIVE");
}

export function editorialProblems(value: EditorialLearning, cards: EditorialCard[], projectId: string, bookId: string): string[] {
  const problems: string[] = [];
  if (value.book_id !== bookId) problems.push("编辑讨论属于另一部作品，请重新登记。");
  if (!value.reader_promise.trim()) problems.push("请说明要保留的类型与阅读体验。");
  if (!value.decisions.length || value.decisions.length > 12 || value.decisions.every(item => item.choice === "DEFER")) problems.push("需要至少一项准备应用的编辑取舍，最多十二项。");
  const eligible = new Map(eligibleEditorialCards(cards, projectId).map(card => [card.asset_version_id, card.content_hash]));
  for (const item of value.decisions) {
    if ([item.finding, item.application, item.reader_effect, item.tradeoff].some(text => !text.trim() || text.length > 2000)) problems.push("每项取舍都需要发现、原创应用、阅读效果和副作用。");
    if (!item.targets.length || item.chapter_range[0] < 1 || item.chapter_range[0] > item.chapter_range[1] || item.chapter_range[1] > 10000) problems.push("请限定取舍的设计阶段和章节范围。");
    if (item.choice !== "DEFER" && !item.knowledge_cards.length) problems.push("准备应用的取舍必须绑定已批准的抽象知识。");
    if (item.knowledge_cards.some(card => eligible.get(card.asset_version_id) !== card.content_hash)) problems.push("所选知识版本已变化或暂不可用，请重新核对；原记录保留。");
  }
  return [...new Set(problems)];
}

export function editorialBriefExtension(value?: EditorialLearning) {
  if (!value) return {creative_brief_contract_version: "creative-brief-v2", input_asset_version_ids: [] as string[]};
  return {
    creative_brief_contract_version: "creative-brief-v4", editorial_learning: value,
    input_asset_version_ids: [...new Set(value.decisions.flatMap(item => item.knowledge_cards.map(card => card.asset_version_id)))].sort(),
  };
}
