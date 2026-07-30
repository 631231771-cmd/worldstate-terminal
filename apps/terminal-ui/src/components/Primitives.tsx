import type { ComponentChildren } from "preact";

export function Panel({
  title,
  eyebrow,
  children,
  className = "",
  aside,
}: {
  title: string;
  eyebrow?: string;
  children: ComponentChildren;
  className?: string;
  aside?: ComponentChildren;
}) {
  return (
    <section class={`panel ${className}`}>
      <header class="panel__header">
        <div>
          {eyebrow ? <div class="eyebrow">{eyebrow}</div> : null}
          <h2>{title}</h2>
        </div>
        {aside ? <div class="panel__aside">{aside}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ComponentChildren;
  tone?: "neutral" | "good" | "warn" | "bad" | "info";
}) {
  return <span class={`badge badge--${tone}`}>{children}</span>;
}

export function StateMessage({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ComponentChildren;
}) {
  return (
    <div class="state-message">
      <div class="state-message__mark">WS</div>
      <div>
        <h2>{title}</h2>
        <p>{detail}</p>
        {action}
      </div>
    </div>
  );
}

export function Meter({ value }: { value: number }) {
  const normalized = Math.max(0, Math.min(1, value));
  return (
    <div class="meter" aria-label={`置信度 ${Math.round(normalized * 100)}%`}>
      <span style={{ width: `${normalized * 100}%` }} />
    </div>
  );
}
