import type { ReactNode } from "react";
import { Sidebar } from "@/components/sidebar";
export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="app-shell"><Sidebar /><div className="app-column"><header className="topbar"><div><div className="topbar-title">Operational workspace</div><div className="topbar-subtitle">Local-first control surface</div></div><div className="workspace-chip" aria-label="Default workspace context"><span className="workspace-dot" aria-hidden="true" /><span>Default workspace</span></div></header><main className="main-content">{children}</main></div></div>;
}
