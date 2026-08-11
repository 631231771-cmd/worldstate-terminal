import { useEffect } from "preact/hooks";
import type { ComponentChildren } from "preact";

export function Panel({ title, eyebrow, children, className = "", aside }: { title: string; eyebrow?: string; children: ComponentChildren; className?: string; aside?: ComponentChildren }) {
  return <section class={`panel ${className}`}><header class="panel__header"><div>{eyebrow ? <div class="eyebrow">{eyebrow}</div> : null}<h2>{title}</h2></div>{aside ? <div class="panel__aside">{aside}</div> : null}</header>{children}</section>;
}

export function Badge({ children, tone = "neutral" }: { children: ComponentChildren; tone?: "neutral" | "good" | "warn" | "bad" | "info" }) {
  return <span class={`badge badge--${tone}`}>{children}</span>;
}

export function StateMessage({ title, detail, action }: { title: string; detail: string; action?: ComponentChildren }) {
  return <div class="state-message"><div class="state-message__mark">WS</div><div><h2>{title}</h2><p>{detail}</p>{action}</div></div>;
}

export function Meter({ value }: { value: number }) {
  const normalized = Math.max(0, Math.min(1, value));
  return <div class="meter" aria-label={`Confidence ${Math.round(normalized * 100)}%`}><span style={{ width: `${normalized * 100}%` }} /></div>;
}

export function Sparkline({ values, tone = "neutral" }: { values?: number[]; tone?: "neutral" | "up" | "down" }) {
  if (!values || values.length < 2) return <span class="sparkline sparkline--empty">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((value, index) => `${((index / (values.length - 1)) * 100).toFixed(1)},${(28 - ((value - min) / span) * 24).toFixed(1)}`).join(" ");
  return <svg class={`sparkline sparkline--${tone}`} viewBox="0 0 100 30" role="img" aria-label="Trend"><polyline points={points} fill="none" vector-effect="non-scaling-stroke" /></svg>;
}

export function DetailsDisclosure({ label, children }: { label: string; children: ComponentChildren }) {
  return <details class="details-disclosure"><summary>{label}</summary><div class="details-disclosure__body">{children}</div></details>;
}

export function Modal({ title, children, onClose }: { title: string; children: ComponentChildren; onClose: () => void }) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  return <div class="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}><section class="modal" role="dialog" aria-modal="true" aria-label={title}><header class="modal__header"><h2>{title}</h2><button class="modal__close" type="button" aria-label="Close" onClick={onClose}>×</button></header><div class="modal__body">{children}</div></section></div>;
}

export function Drawer({ title, children, onClose }: { title: string; children: ComponentChildren; onClose: () => void }) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  return <div class="drawer-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside class="drawer" role="dialog" aria-modal="true" aria-label={title}><header class="drawer__header"><h2>{title}</h2><button type="button" class="drawer__close" aria-label="Close" onClick={onClose}>×</button></header><div class="drawer__body">{children}</div></aside></div>;
}
