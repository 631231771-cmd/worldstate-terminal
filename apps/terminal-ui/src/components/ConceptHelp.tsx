import { useState } from "preact/hooks";
import { CONCEPTS, type ConceptKey } from "../learning/concepts";

export function ConceptHelp({ concept, active }: { concept: ConceptKey; active: boolean }) {
  const [open, setOpen] = useState(false);
  if (!active) return null;
  const item = CONCEPTS[concept];
  return <span class="concept-help">
    <button type="button" class="concept-help__trigger" aria-label={`解释：${item.title}`} aria-expanded={open} onClick={() => setOpen((value) => !value)}>?</button>
    {open ? <span class="concept-help__popover" role="note"><strong>{item.title}</strong><span>{item.explanation}</span><span>{item.whyItMatters}</span></span> : null}
  </span>;
}

export function ConceptStrip({ concepts, active }: { concepts: ConceptKey[]; active: boolean }) {
  if (!active) return null;
  return <div class="concept-strip">{concepts.map((concept) => <span key={concept}>{CONCEPTS[concept].title}<ConceptHelp concept={concept} active /></span>)}</div>;
}
