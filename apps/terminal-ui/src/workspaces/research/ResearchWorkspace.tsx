import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";

export function ResearchWorkspace({ selectedId, onSelect }: { selectedId?: string | null; onSelect?: (id: string) => void }) {
  const [theses, setTheses] = useState<Array<Record<string, unknown>>>([]);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [evaluation, setEvaluation] = useState<Record<string, unknown> | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");

  const open = async (item: Record<string, unknown>) => {
    setSelected(item); setEvaluation(null);
    if (item.id) {
      onSelect?.(String(item.id));
      setEvaluation(await api.evaluateThesis(String(item.id)).catch(() => null));
    }
  };
  const refresh = () => void api.theses().then((items) => {
    setTheses(items);
    const requested = selectedId ? items.find((item) => String(item.id) === selectedId) : null;
    if (requested) void open(requested);
  }).catch(() => setTheses([]));
  useEffect(refresh, []);
  useEffect(() => {
    if (!selectedId || selected?.id === selectedId) return;
    const item = theses.find((row) => String(row.id) === selectedId);
    if (item) void open(item);
  }, [selectedId, theses]);

  const save = async () => {
    if (!title.trim() || !text.trim()) return;
    const created = await api.createThesis({ title, thesis: text, horizon: "3m" });
    setTitle(""); setText(""); await open(created); refresh();
  };

  return <div class="workspace">
    <section class="page-heading page-heading--compact"><div><div class="eyebrow">RESEARCH / THESIS BOOK</div><h1>我的研究判断</h1><p>把宏观判断、支持条件、反证条件和观察变量放在一起。系统提示新证据，但不会替你修改观点。</p></div></section>
    <div class="two-column two-column--research">
      <Panel title="新建 Thesis" eyebrow="USER OWNED"><input class="search-input thesis-input" value={title} onInput={(event) => setTitle(event.currentTarget.value)} placeholder="例如：增长放缓但金融条件稳定" /><textarea class="thesis-textarea" value={text} onInput={(event) => setText(event.currentTarget.value)} placeholder="写下判断、时间范围和关键条件…" /><button type="button" class="primary-button" onClick={() => void save()}>保存判断</button><p class="method-note">保存为用户拥有的 observed 研究记录；证据关联由用户明确确认。</p></Panel>
      <Panel title={selected ? String(selected.title) : "选择一个判断"} eyebrow="EVIDENCE CHECK"><div class="thesis-list">{theses.map((item) => <button type="button" class={selected?.id === item.id ? "thesis-row active" : "thesis-row"} key={String(item.id)} onClick={() => void open(item)}><span><strong>{String(item.title)}</strong><small>{String(item.horizon)} · {String(item.status)}</small></span><Badge tone={item.status === "active" ? "good" : "warn"}>{Math.round(Number(item.confidence ?? 0.5) * 100)}%</Badge></button>)}{!theses.length ? <StateMessage title="还没有研究判断" detail="把你正在跟踪的宏观链条写下来。" /> : null}</div>{evaluation ? <><h3>当前状态信号</h3>{((evaluation.state_signals as Array<Record<string, unknown>>) ?? []).map((signal) => <div class="driver-row" key={String(signal.dimension)}><strong>{String(signal.dimension)}</strong><span>{signal.score == null ? "—" : Number(signal.score).toFixed(2)} · {String(signal.direction)}</span></div>)}<p class="method-note">{String(evaluation.interpretation)}</p></> : <p class="muted">选择 Thesis 查看当前状态与证据线索。</p>}</Panel>
    </div>
  </div>;
}
