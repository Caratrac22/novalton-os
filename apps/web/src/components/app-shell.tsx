import type { ReactNode } from "react";
import { Sidebar } from "@/components/sidebar";

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="app-shell"><Sidebar /><div className="app-column"><header className="topbar"><div><div className="topbar-title">Novalton OS</div><div className="topbar-subtitle">Espace personnel de projets et de supervision</div></div><div className="workspace-chip" aria-label="Application web locale"><span className="workspace-dot" aria-hidden="true" /><span>Console web</span></div></header><main id="main-content" className="main-content">{children}</main></div></div>;
}
