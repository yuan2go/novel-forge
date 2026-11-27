"use client";

import { useEffect, useState } from "react";
import { fetchJson, postJson } from "../../shared/api";

type Capture = { operation_id: string; status: string; asset_version_id?: string; snapshot?: { mode: string; acquired_at: string; ranking_period: string | null } };
type Work = { work_id: string; title: string; author: string | null; category: string | null; subcategory: string | null; serial_status: string | null; synopsis: string | null; detail_url: string; rank: number | null; metric_value: number | null; synopsis_scope: string };
type Snapshot = { asset_version_id: string; snapshot: { mode: string; acquired_at: string; url: string } };
type Page = { items: Work[]; next_after: string; mode: string; acquired_at: string; ranking_period: string | null };

export function PublicCatalogPanel() {
  const [project, setProject] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [url, setUrl] = useState("");
  const [platform, setPlatform] = useState("qidian");
  const [pages, setPages] = useState(1);
  const [pending, setPending] = useState<{ key: string; body: Record<string, unknown> } | null>(null);
  const [capture, setCapture] = useState<Capture | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("");
  const [serialStatus, setSerialStatus] = useState("");
  const [page, setPage] = useState<Page | null>(null);
  const [selected, setSelected] = useState<Work | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const storageKey = "novel-forge:public-catalog:v1";
  const [selectionPending, setSelectionPending] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
      setProject(saved.project || ""); setWorkspace(saved.workspace || ""); setPending(saved.pending || null);
      setCapture(saved.capture || null); setSelectionPending(saved.selectionPending || null);
      setUrl(saved.url || ""); setSnapshotId(saved.snapshotId || ""); setSelected(saved.selected || null);
    } catch { setError("本机原请求读取失败，请保留记录后恢复存储。"); }
    setReady(true);
  }, []);
  function retain(overrides: Record<string, unknown> = {}) {
    localStorage.setItem(storageKey, JSON.stringify({project, workspace, pending, capture, selectionPending, url, snapshotId, selected, ...overrides}));
  }
  useEffect(() => { if (ready) { try { retain(); } catch { setError("本机请求保存失败，请恢复存储后继续。"); } } }, [ready, project, workspace, pending, capture, selectionPending, url, snapshotId, selected]);

  async function action(run: () => Promise<void>) {
    setBusy(true); setError("");
    try { await run(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  async function captureCatalog() {
    const request = pending || { key: crypto.randomUUID(), body: { project_id: project, workspace_id: workspace,
      idempotency_key: crypto.randomUUID(), capture: { platform, url, max_pages: pages, mode: "LIVE_HTTP" } } };
    retain({pending: request}); setPending(request);
    const result = await postJson("/product/source-governance/public-catalog/captures", request.body) as Capture;
    retain({capture: result, pending: null}); setCapture(result); setPending(null);
    setNotice("采集已登记。读取任务状态后才能确认成功；失败不表示榜单为空。");
  }
  async function status() {
    if (!capture) return;
    const result = await fetchJson<Capture>(`/product/source-governance/public-catalog/captures/${encodeURIComponent(capture.operation_id)}?project_id=${encodeURIComponent(project)}`);
    setCapture(result);
    if (result.asset_version_id) setSnapshotId(result.asset_version_id);
    setNotice(`任务状态：${result.status}`);
  }
  async function history() {
    const rows = await fetchJson<Snapshot[]>(`/product/source-governance/public-catalog/snapshots?project_id=${encodeURIComponent(project)}&limit=100`);
    setSnapshots(rows);
    if (rows.length && !snapshotId) setSnapshotId(rows[0].asset_version_id);
  }
  async function query(after = "") {
    const params = new URLSearchParams({ project_id: project, snapshot_id: snapshotId, keyword, category, serial_status: serialStatus, after, limit: "20" });
    setPage(await fetchJson<Page>(`/product/source-governance/public-catalog/works?${params}`)); setSelected(null);
  }
  async function selectResearch() {
    if (!selected) return;
    const body = selectionPending || { project_id: project, workspace_id: workspace, snapshot_id: snapshotId,
      work_id: selected.work_id, idempotency_key: crypto.randomUUID() };
    retain({selectionPending: body}); setSelectionPending(body);
    const result = await postJson("/product/source-governance/public-catalog/research-selections", body) as { operation_id: string };
    retain({selectionPending: null}); setSelectionPending(null); setNotice(`研究候选登记任务：${result.operation_id}。正文尚未导入；榜单不授予正文或生成权限。`);
  }
  return <section className="panel" aria-label="热门作品查询">
    <h2>热门作品查询</h2>
    <p className="mutedText">公开榜单用于发现研究候选。快照保留来源与采集时间；缺失数字如实留空。离线快照不会标为实时成功。</p>
    <div className="formGrid">
      <input aria-label="项目 ID" placeholder="项目 ID" value={project} disabled={!!pending || !!selectionPending} onChange={e => setProject(e.target.value)} />
      <input aria-label="工作区 ID" placeholder="工作区 ID" value={workspace} disabled={!!pending || !!selectionPending} onChange={e => setWorkspace(e.target.value)} />
      <select aria-label="来源平台" value={platform} disabled={!!pending} onChange={e => setPlatform(e.target.value)}><option value="qidian">起点官方公开页</option></select>
      <input aria-label="官方榜单或详情 URL" placeholder="官方榜单或详情 URL" value={url} disabled={!!pending} onChange={e => setUrl(e.target.value)} />
      <input aria-label="采集页数" type="number" min={1} max={5} value={pages} disabled={!!pending} onChange={e => setPages(Number(e.target.value))} />
    </div>
    <div className="buttonRow">
      <button disabled={busy || !project || !workspace || !url} onClick={() => action(captureCatalog)}>{pending ? "使用原请求对账" : "采集公开页"}</button>
      <button disabled={busy || !capture} onClick={() => action(status)}>读取任务状态</button>
      <button disabled={busy || !project} onClick={() => action(history)}>读取快照</button>
    </div>
    {snapshots.length > 0 && <select aria-label="来源快照" value={snapshotId} disabled={!!selectionPending} onChange={e => setSnapshotId(e.target.value)}>{snapshots.map(s => <option key={s.asset_version_id} value={s.asset_version_id}>{s.snapshot.mode} · {s.snapshot.acquired_at} · {s.snapshot.url}</option>)}</select>}
    <input aria-label="快照 ID" placeholder="快照 ID" value={snapshotId} disabled={!!selectionPending} onChange={e => setSnapshotId(e.target.value)} />
    <div className="formGrid">
      <input aria-label="作品或作者关键词" placeholder="作品或作者关键词" value={keyword} onChange={e => setKeyword(e.target.value)} />
      <input aria-label="分类筛选" placeholder="分类名称，可留空" value={category} onChange={e => setCategory(e.target.value)} />
      <select aria-label="连载状态" value={serialStatus} onChange={e => setSerialStatus(e.target.value)}><option value="">全部状态</option><option>连载</option><option>完本</option></select>
    </div>
    <button disabled={busy || !!selectionPending || !snapshotId || !project} onClick={() => action(() => query())}>筛选快照作品</button>
    {page && <>
      <p>{page.mode} · 采集：{page.acquired_at} · 榜期：{page.ranking_period || "未公布"} · 数据更新时间：未公布</p>
      <table><thead><tr><th>名次</th><th>作品</th><th>作者</th><th>分类</th><th>状态</th></tr></thead><tbody>{page.items.map(work => <tr key={work.work_id}><td>{work.rank ?? "—"}</td><td><button disabled={!!selectionPending} onClick={() => setSelected(work)}>{work.title}</button></td><td>{work.author || "—"}</td><td>{[work.category, work.subcategory].filter(Boolean).join(" · ")}</td><td>{work.serial_status || "—"}</td></tr>)}</tbody></table>
      {!page.items.length && <p>该成功快照在当前筛选下没有匹配作品。</p>}
      {page.next_after && <button disabled={busy || !!selectionPending} onClick={() => action(() => query(page.next_after))}>下一页结果</button>}
    </>}
    {selected && <article><h3>{selected.title}</h3><p>{selected.synopsis || "简介未取得"}</p><p>范围：{selected.synopsis_scope} · 作品 ID：{selected.work_id} · 榜单指标：{selected.metric_value ?? "未取得"}</p><a href={selected.detail_url} target="_blank" rel="noreferrer">查看官方来源</a> <button disabled={busy || !workspace} onClick={() => action(selectResearch)}>{selectionPending ? "对账原研究选择" : "选入研究候选"}</button></article>}
    {capture && <p>采集任务：{capture.operation_id} · {capture.status}</p>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="errorLine">{error}</p>}
  </section>;
}
