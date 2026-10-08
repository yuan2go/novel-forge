import { fetchJson } from "../../shared/api";
import type { ProjectRow } from "../../shared/types";

const prefix = "/product/production/book-authority";
export type Book = { book_id: string; workspace_id: string; title: string; version: number; status: string; production_profile: Record<string, unknown>; runtime_policy: Record<string, unknown> };
export type Profile = { asset_version_id: string; content_hash: string; content: Record<string, unknown> };
export type Snapshot = { snapshot_id: string; snapshot_hash: string; release_sha: string; production_profile_version: string; narrative_chapter_cursor: number; [key: string]: unknown };
export type EditorialControl = {policy: {policy_version: string; mode: string}; content_hash: string; selected_by_operation_id?: string; subject_id?: string};
export type Run = { frozen_editorial_control?: EditorialControl | null; book_run_id: string; state: string; accepted_through_chapter: number; target_chapter_count: number; active_chapter_request_id: string; input_snapshot_id: string; production_profile_version: string; frozen_profile: Record<string, unknown> | null; chapter_configuration?: Record<string, unknown>; profile_hash: string; failure_reason: string; paused_reason: string; version: number };
export type Workspace = { formation_run_id?: string; editorial_control?: EditorialControl | null; approved_characters?: Array<{character_id: string; name: string; source_asset_version_id: string; source_content_hash: string}>; release_identity?: string; dispatch_control?: {state: string; reason: string; process_dispatch_suspended: boolean}; books: Book[]; runs: Run[]; profiles: Profile[]; snapshots: Snapshot[]; budget_scopes: Array<{ budget_scope_id: string; owner_kind: string; owner_id: string; deadline_at: string; expired: boolean; policy: Record<string, unknown> }> };
export type Progress = { state: string; blocking_reason: string; blocking_class: string; wake_condition: string; next_expected_transition: string; active_operation_id: string; active_operation_status: string; [key: string]: unknown };
function post<T>(path: string, body: Record<string, unknown>) { return fetchJson<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
export function loadProductionProjects() { return fetchJson<ProjectRow[]>("/product/projects"); }
export function loadProductionWorkspace(projectId: string, bookId = "") { return fetchJson<Workspace>(`${prefix}/author-workspace?${new URLSearchParams({ project_id: projectId, book_id: bookId })}`); }
export function resolveProductionSnapshot(projectId: string, book: Book, profile: string, cursor: number, idempotencyKey: string) {
  return post<Snapshot>(`${prefix}/books/${encodeURIComponent(book.book_id)}/production-inputs/resolve`, { project_id: projectId, workspace_id: book.workspace_id, production_profile: profile, expected_book_version: book.version, narrative_chapter_cursor: cursor, idempotency_key: idempotencyKey });
}
export function startBookProduction(body: Record<string, unknown>) { return post<{ book_run_id: string; replayed: boolean }>(`${prefix}/commands`, body); }
export function pauseBookProduction(run: string, reason: string) { return post<Run>(`${prefix}/runs/${encodeURIComponent(run)}/pause`, { reason }); }
export function resumeBookProduction(run: string, reason: string) { return post<Run>(`${prefix}/runs/${encodeURIComponent(run)}/resume`, { reason }); }
export function cancelBookProduction(run: string, reason: string) { return post<Run>(`${prefix}/runs/${encodeURIComponent(run)}/cancel`, { reason }); }
export function recoverBookChapter(requestId: string) { return post<Record<string, unknown>>(`${prefix}/chapter-requests/${encodeURIComponent(requestId)}/recover`, {}); }
export function loadBookProgress(run: string) { return fetchJson<Progress>(`${prefix}/runs/${encodeURIComponent(run)}/progress`); }

export type ContentOperation = { operation_id: string; status: string; outputs: Array<{asset_version_id: string; content_hash: string}> };
export type FormationCandidate = {asset_version_id: string; content_hash: string; content: Record<string, unknown>; state: Record<string, unknown>};
export type CreationStatus = {author_state: string; next_action?: string; responsible_party?: string; failure?: {code?: string; message?: string}; production?: {book_run_id: string; state: string; accepted_chapters: number; saved_chapters: number; target_chapters: number; version: number} | null; stage: string; cancellation: unknown; coordination: {status: string; next_attempt_at?: string; error?: unknown; result?: {wait_class?: string; stop_reason?: string; next_action?: string}} | null; progress: unknown[]};
export type Formation = { creation?: CreationStatus; formation_run_id: string; version: number; lifecycle: string; current_stage: string; failure: unknown; recovery_instruction: {candidate_asset_version_id?: string; author_selection?: {decision: string; reason: string}; generation_failures?: Array<{asset_version_id: string; content_hash: string; reason_code: string}>} | null; candidates?: FormationCandidate[]; author_review_history?: Array<{stage: string; decisions: Array<{decision: string; reason: string; actor_id: string; candidate_asset_version_id: string}>}>; book_design_asset_version_id: string; book_design_content_hash: string };
export function createAuthorBook(body: Record<string, unknown>) { return post<Record<string, unknown>>("/authority/books", body); }
export function saveCreativeInput(body: Record<string, unknown>) { return post<ContentOperation>("/product/content-authority/commands", body); }
export function loadCreativeInput(project: string, operation: string) { return fetchJson<ContentOperation>(`/product/content-authority/operations/${encodeURIComponent(operation)}?${new URLSearchParams({project_id: project})}`); }
export function startFormation(book: string, body: Record<string, unknown>) { return post<Formation>(`${prefix}/books/${encodeURIComponent(book)}/formation-runs`, body); }
export function loadFormation(run: string) { return fetchJson<Formation>(`${prefix}/formation-runs/${encodeURIComponent(run)}`); }
export function resumeFormation(run: Formation, body?: Record<string,unknown>) { return post<Formation>(`${prefix}/formation-runs/${encodeURIComponent(run.formation_run_id)}/resume`, body || {expected_version: run.version}); }

export function createAuthorWorkspace(project: string, body: Record<string, unknown>) { return post<Record<string, unknown>>(`/product/projects/${encodeURIComponent(project)}/workspaces`, body); }

export function submitFormationDecision(run: string, body: Record<string, unknown>) { return post<Formation>(`${prefix}/formation-runs/${encodeURIComponent(run)}/author-decisions`, body); }

export function cancelCreation(run: Formation, body: Record<string, unknown>) { return post<Formation>(`${prefix}/formation-runs/${encodeURIComponent(run.formation_run_id)}/abort`, body); }
