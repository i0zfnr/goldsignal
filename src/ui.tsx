import type { ReactNode } from "react";

type Tone = "neutral" | "accent" | "positive" | "negative";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  return <span className="badge" data-tone={tone}>{children}</span>;
}

export function PanelHeading({ id, title, as: Heading = "h2", children }: {
  id?: string; title: string; as?: "h2" | "h3"; children?: ReactNode;
}) {
  return <div className="panel-heading"><Heading id={id}>{title}</Heading>{children}</div>;
}

export function EmptyState({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return <div className="empty-state" role="status">
    {icon && <span className="empty-icon" aria-hidden="true">{icon}</span>}
    <p>{children}</p>
  </div>;
}

export function Metric({ label, children, note, tone = "neutral" }: {
  label: string; children: ReactNode; note?: ReactNode; tone?: Tone;
}) {
  return <div className="metric" data-tone={tone}>
    <dt>{label}</dt><dd>{children}</dd>{note && <span className="small muted">{note}</span>}
  </div>;
}

export function LoadingState({ children }: { children: ReactNode }) {
  return <div className="loading-state" role="status">{children}<span aria-hidden="true" /></div>;
}
