"use client";

import Link from "next/link";
import {useEffect, useState} from "react";
import {fetchJson} from "../../shared/api";
import {pauseBookProduction, resumeBookProduction} from "./api";

type Unit = {chapter: number; title: string; text: string; asset_version_id: string; content_hash: string;
  requirements_status: string; dependency_changes: unknown[]; review_status: string;
  working_selection?: {status: string; asset_version_id?: string; content_hash?: string; author_selection?: string; formal_acceptance?: string}};
export type Manuscript = {book_run_id: string; book_id: string; workspace_id: string; project_id: string;
  writing_state: string; target_chapters: number; units: Unit[]; text: string; manifest_digest: string; accepted_through_chapter: number};

export function CurrentManuscriptPanel({project, bookRun}: {project: string; bookRun: string}) {
  const [manuscript, setManuscript] = useState<Manuscript | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    setManuscript(await fetchJson<Manuscript>(`/product/editor/manuscripts?${new URLSearchParams({project_id: project, book_run_id: bookRun})}`));
  }
  useEffect(() => {
    let live = true;
    setManuscript(null); setError("");
    const load = () => fetchJson<Manuscript>(`/product/editor/manuscripts?${new URLSearchParams({project_id: project, book_run_id: bookRun})}`)
      .then(value => {if (live) setManuscript(value);}).catch(e => {if (live) setError(String(e));});
    void load(); const timer = setInterval(load, 5000);
    return () => {live = false; clearInterval(timer);};
  }, [project, bookRun]);
  async function control(action: "pause" | "resume") {
    if (!manuscript || busy) return;
    setBusy(true); setError("");
    try {
      await (action === "pause" ? pauseBookProduction(bookRun, "作者暂停写作") : resumeBookProduction(bookRun, "作者继续写作"));
      await refresh();
    } catch (e) {setError(`请求结果需核对，请刷新稿件状态。${String(e)}`);} finally {setBusy(false);}
  }
  async function download() {
    if (!manuscript || busy) return;
    setBusy(true); setError("");
    try {
      const exact = await fetchJson<Manuscript>("/product/editor/manuscripts/export", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({project_id: project, book_run_id: bookRun, version_ids: manuscript.units.map(unit => unit.asset_version_id)})});
      const provenance = `当前稿件 · 审定至第 ${exact.accepted_through_chapter} 章\n稿件版本：${exact.manifest_digest}\n` +
        exact.units.map(unit => `第 ${unit.chapter} 章：${unit.asset_version_id} · 审读 ${unit.review_status} · 要求 ${unit.requirements_status}` +
          (unit.working_selection?.status === "SELECTED" ? ` · 工作稿选用回执 ${unit.working_selection.asset_version_id} · ${unit.working_selection.content_hash}` : "")).join("\n");
      const url = URL.createObjectURL(new Blob([provenance, "\n\n", exact.text], {type: "text/plain;charset=utf-8"}));
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${exact.book_id}-current.txt`; anchor.click(); URL.revokeObjectURL(url);
    } catch (e) {setError(String(e));} finally {setBusy(false);}
  }
  return <section className="panel"><h2>当前稿件</h2>
    <p>正文保存后即可阅读、修改和导出。未审稿件不代表质量通过；前文变化时保留后文并提示实际版本依赖。</p>
    <div className="studioActions"><button disabled={busy} onClick={() => refresh().catch(e => setError(String(e)))}>刷新稿件</button>
      <button className="primaryButton" disabled={busy || !manuscript?.units.length} onClick={download}>导出当前稿件</button>
      <button disabled={busy || !manuscript || manuscript.writing_state === "PAUSED"} onClick={() => control("pause")}>暂停写作</button>
      <button disabled={busy || manuscript?.writing_state !== "PAUSED"} onClick={() => control("resume")}>继续写作</button></div>
    {manuscript?.units.map(unit => <details key={unit.asset_version_id}><summary>第 {unit.chapter} 章 {unit.title} · 已保存 · {unit.review_status === "NOT_RUN" ? "未审读" : unit.review_status}</summary>
      {unit.working_selection?.status === "SELECTED" && <p>工作稿已选用 · 回执 {unit.working_selection.asset_version_id} · 作者认可 {unit.working_selection.author_selection} · 正式接纳 {unit.working_selection.formal_acceptance}</p>}
      {unit.dependency_changes.length > 0 && <p role="status">前文选定版本已变化；此章保留，需检查受影响的连续性。</p>}
      <Link href={`/editor?${new URLSearchParams({project_id: project, book_id: manuscript.book_id, book_run_id: bookRun, base_asset_version_id: unit.asset_version_id})}`}>修改本章、查看差异、按需审读</Link>
      <p style={{whiteSpace: "pre-wrap"}}>{unit.text}</p></details>)}
    {manuscript && !manuscript.units.length && <p>尚无完整保存的正文。</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
