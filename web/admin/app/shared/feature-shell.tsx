"use client";

import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { ConsoleShell } from "./console-shell";

type FeatureShellProps = {
  title: string;
  subtitle: string;
  eyebrow?: string;
  backLabel?: string;
  children: ReactNode;
};

export function FeatureShell({
  title,
  subtitle,
  eyebrow = "Novel Forge Feature",
  backLabel: _backLabel = "返回总控台",
  children
}: FeatureShellProps) {
  return (
    <ConsoleShell>
      <header className="manuscriptHeader panel">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <div className="studioActions">
          <button className="secondaryButton" onClick={() => window.location.reload()}>
            <RefreshCw size={18} />
            刷新
          </button>
        </div>
      </header>
      {children}
    </ConsoleShell>
  );
}
