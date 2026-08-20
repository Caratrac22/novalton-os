import type { ReactNode } from "react";
export type StatusTone = "positive" | "negative" | "neutral";
export function StatusBadge({ children, tone }: Readonly<{ children: ReactNode; tone: StatusTone }>) { return <span className="status-badge" data-tone={tone}>{children}</span>; }
