import { fetchJson } from "../../shared/api";
import type { ProjectRow } from "../../shared/types";

export type EditorScope = { project_id: string; workspace_id: string; book_id: string; chapter: number };
export type EditorDraft = EditorScope & { asset_version_id: string; asset_type: string; title: string; content_hash: string };
export type EditorCandidate = { asset_version_id: string; content_hash: string; content: {
  text: string; text_hash: string; status: string; base_asset_version_id: string;
  edits: Array<{start: number; end: number; before: string; after: string}>;
} };
export type DraftEditorState = EditorScope & {
  base_asset_version_id: string; base_asset_hash: string; base_text_hash: string; text: string; title: string;
  book_runs: string[];
  book_request: {chapter_request_id: string; book_run_id: string; root_operation_id: string; book_version: number; is_current: boolean; unaccepted: boolean} | null;
  version: number; candidates: EditorCandidate[]; decisions: Array<{asset_version_id: string; content: Record<string, unknown>}>;
  diagnostics: Array<{asset_version_id: string; content: {issues?: Array<{code: string; message: string; severity: string}>}}>;
  session: {status: string; candidate_asset_version_id: string; decision_asset_version_id: string} | null;
};
export type EditorCommand = EditorScope & {
  action: "save" | "accept" | "reject"; base_asset_version_id: string; base_asset_hash: string;
  base_text_hash: string; expected_version: number; idempotency_key: string;
  text?: string; rights_basis?: "ORIGINAL_AUTHOR_INPUT" | "AUTHORIZED_INPUT";
  allowed_ranges?: Array<{start: number; end: number}>; candidate_asset_version_id?: string; rationale?: string;
  source_review_run_id?: string; source_lineage_id?: string;
};
export type EditorResult = {version: number; candidate_asset_version_id: string; decision_asset_version_id: string; editor_status: string; replayed: boolean};

export function loadEditorProjects() { return fetchJson<ProjectRow[]>("/product/projects"); }
export function loadEditorDrafts(projectId: string) {
  return fetchJson<EditorDraft[]>(`/product/editor/drafts?project_id=${encodeURIComponent(projectId)}`);
}
export function loadDraftEditor(draft: EditorDraft) {
  const params = new URLSearchParams({ project_id: draft.project_id, workspace_id: draft.workspace_id,
    book_id: draft.book_id, chapter: String(draft.chapter), base_asset_version_id: draft.asset_version_id });
  return fetchJson<DraftEditorState>(`/product/editor/draft?${params}`);
}
export function submitEditorCommand(body: EditorCommand) {
  return fetchJson<EditorResult>("/product/editor/commands", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
}
export function requestAuthorReview(state: DraftEditorState, idempotencyKey: string) {
  if (state.book_request) return fetchJson<{root_operation_id: string; query_url: string}>("/product/editor/book-reviews", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
      project_id: state.project_id, workspace_id: state.workspace_id, book_id: state.book_id,
      chapter_request_id: state.book_request.chapter_request_id, expected_book_version: state.book_request.book_version,
      expected_root_operation_id: state.book_request.root_operation_id,
      candidate_asset_version_id: state.session?.candidate_asset_version_id, decision_asset_version_id: state.session?.decision_asset_version_id,
      idempotency_key: idempotencyKey})});
  return fetchJson<{root_operation_id: string; query_url: string}>("/product/production/chapter-authority/commands", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
      project_id: state.project_id, workspace_id: state.workspace_id, book_id: state.book_id, chapter: state.chapter,
      idempotency_key: idempotencyKey, author_candidate_asset_version_id: state.session?.candidate_asset_version_id,
      author_decision_asset_version_id: state.session?.decision_asset_version_id
    })
  });
}

export type AuthorReviewStatus = {root_operation_id: string; run: {status: string; operations: Array<{operation_id: string; definition_name: string; status: string}>}; acceptance: {status: string} | null; artifacts: Record<string, Array<{asset_version_id: string; asset_type: string; content: Record<string, unknown>}>>};
export function loadAuthorReview(projectId: string, rootOperationId: string) {
  return fetchJson<AuthorReviewStatus>(`/product/production/chapter-authority/run?${new URLSearchParams({project_id: projectId, root_operation_id: rootOperationId, include_workspace: "true"})}`);
}
