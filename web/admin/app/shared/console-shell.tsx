"use client";

import { Bell, Languages, RefreshCw, Search } from "lucide-react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "./api";
import { navGroups, navItemForPath } from "./navigation";
import type { Health, ProjectHealthReport, ProjectRow } from "./types";

type ConsoleShellProps = {
  children: ReactNode;
};

export function ConsoleShell({ children }: ConsoleShellProps) {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [projectHealth, setProjectHealth] = useState<ProjectHealthReport | null>(null);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  const [search, setSearch] = useState("");

  const selectedProject = projects[0];
  const current = useMemo(() => navItemForPath(pathname), [pathname]);
  const dataSyncOk = Boolean(health?.configured_services?.postgresql || health?.local_counts);
  const modelOk = Boolean(projectHealth?.embedding?.ok);
  const riskCount =
    (projectHealth?.summary.failed_task_count ?? 0) +
    (projectHealth?.summary.pending_handoff_count ?? 0) +
    (projectHealth?.summary.scope_issue_count ?? 0) +
    (projectHealth?.summary.dead_letter_count ?? 0);

  async function refreshStatus() {
    const [healthData, projectRows, projectHealthData] = await Promise.all([
      fetchJson<Health>("/health"),
      fetchJson<ProjectRow[]>("/product/projects"),
      fetchJson<ProjectHealthReport>("/product/system/health")
    ]);
    setHealth(healthData);
    setProjects(projectRows);
    setProjectHealth(projectHealthData);
  }

  useEffect(() => {
    refreshStatus().catch(() => undefined);
  }, []);

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    const query = search.trim();
    if (query) window.location.href = `/assets?keyword=${encodeURIComponent(query)}`;
  }

  return (
    <div className="factoryShell">
      <aside className="factorySidebar">
        <div className="factoryBrand">
          <span className="localModeBadge">{language === "zh" ? "本地模式" : "Local Mode"}</span>
          <h1>Novel Forge</h1>
          <p>{language === "zh" ? "个人本地小说工厂控制台" : "Personal local novel factory"}</p>
        </div>

        <div className="projectBadge">
          <span>{language === "zh" ? "当前项目" : "Current Project"}</span>
          <strong>{selectedProject?.title || (language === "zh" ? "未选择项目" : "No project selected")}</strong>
          <small>{selectedProject?.path || selectedProject?.project_id || "local workspace"}</small>
        </div>

        <nav className="sidebarNav">
          {navGroups.map((group) => (
            <div className="navGroup" key={group.key}>
              <p>{group.label}</p>
              {group.items.map((item) => {
                const hrefPath = item.href.split("?")[0];
                const active = pathname === hrefPath || (pathname === "/" && item.href === "/");
                return (
                  <a key={item.key} className={active ? "navItem active" : "navItem"} href={item.href} title={item.description}>
                    {item.icon}
                    <span>{item.label}</span>
                  </a>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>

      <main className="factoryWorkspace">
        <div className="factoryTopbar">
          <div className="statusStrip">
            <span className="statusPill ok">{language === "zh" ? "本地生产" : "Local production"}</span>
            <span className={dataSyncOk ? "statusPill ok" : "statusPill warn"}>{language === "zh" ? "数据同步" : "Data sync"}: {dataSyncOk ? "ready" : "attention"}</span>
            <span className={modelOk ? "statusPill ok" : "statusPill warn"}>{language === "zh" ? "模型状态" : "Model"}: {modelOk ? "ready" : "attention"}</span>
            <span className="statusPill ok">{language === "zh" ? "自动保存" : "Autosave"}: on</span>
          </div>
          <div className="topbarTools">
            <form className="globalSearch" onSubmit={submitSearch}>
              <Search size={16} />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={language === "zh" ? "搜索资产、任务、章节" : "Search assets, tasks, chapters"} />
            </form>
            <button className="secondaryButton" onClick={() => setLanguage(language === "zh" ? "en" : "zh")}>
              <Languages size={18} />
              {language === "zh" ? "EN" : "中文"}
            </button>
            <button className="secondaryButton" onClick={() => refreshStatus()}>
              <RefreshCw size={18} />
              {language === "zh" ? "刷新" : "Refresh"}
            </button>
            <span className={riskCount ? "notificationPill warn" : "notificationPill"}>
              <Bell size={16} />
              {riskCount}
            </span>
          </div>
        </div>

        <header className="factoryPageHeader">
          <div>
            <p className="eyebrow">{current?.description || "Novel Forge Console"}</p>
            <h2>{current?.label || "工作台"}</h2>
          </div>
          <div className="pageHeaderMeta">
            <span className="statusPill muted">root: {health?.root || "local"}</span>
            <span className={projectHealth?.postgres?.ready ? "statusPill ok" : "statusPill warn"}>Postgres: {projectHealth?.postgres?.ready ? "ready" : "attention"}</span>
          </div>
        </header>

        <div className="factoryPageBody">{children}</div>
      </main>
    </div>
  );
}
