import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";

export function ResearchWorkspace() {
  const [theses, setTheses] = useState<Array<Record<string, unknown>>>([]);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [evaluation, setEvaluation] = useState<Record<string, unknown> | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");

  const refresh = () => void api.theses().then(setTheses).catch(() => setTheses([]));
  useEffect(refresh, []);

  const save = async () => {
    if (!title.trim() || !text.trim()) return;
    const created = await api.createThesis({ title, thesis: text, horizon: "3m" });
    setTitle(""); setText(""); setSelected(created); refresh();
  };

  const open = async (item: Record<string, unknown>) => {
    setSelected(item);
    setEvaluation(null);
    if (item.id) setEvaluation(await api.evaluateThesis(String(item.id)).catch(() => null));
  };

  return <div class="workspace">
    <section class="page-heading"><div class="eyebrow">RESEARCH · THESIS BOOK</div><h1>我的研究判断</h1><p>把宏观判断、确认条件、证伪条件和观察变量放在一起。系统可以提示新证据，但不会替你修改观点。</p></section>
    <div class="two-column two-column--research">
      <Panel title="新建 Thesis" eyebrow="USER OWNED"><input class="search-input thesis-input" value={title} onInput={(event) => setTitle((event.currentTarget as HTMLInputElement).value)} placeholder="标题，例如：增长放缓但金融条件稳定" /><textarea class="thesis-textarea" value={text} onInput={(event) => setText((event.currentTarget as HTMLTextAreaElement).value)} placeholder="写下你的判断、时间范围和关键条件…" /><button type="button" class="primary-button" onClick={() => void save()}>保存判断</button><p class="method-note">保存后 data_mode 为 observed；引用证据由用户明确关联。</p></Panel>
      <Panel title={selected ? String(selected.title) : "选择一个判断"} eyebrow="EVIDENCE CHECK"><div class="thesis-list">{theses.map((item) => <button type="button" class={selected?.id === item.id ? "thesis-row active" : "thesis-row"} key={String(item.id)} onClick={() => void open(item)}><span><strong>{String(item.title)}</strong><small>{String(item.horizon)} · {String(item.status)}</small></span><Badge tone={item.status === "active" ? "good" : "warn"}>{Math.round(Number(item.confidence ?? 0.5) * 100)}%</Badge></button>)}{!theses.length ? <StateMessage title="还没有研究判断" detail="把你正在跟踪的宏观链条写下来。" /> : null}</div>{evaluation ? <><h3>当前状态信号</h3>{((evaluation.state_signals as Array<Record<string, unknown>>) ?? []).map((signal) => <div class="driver-row" key={String(signal.dimension)}><strong>{String(signal.dimension)}</strong><span>{signal.score == null ? "—" : Number(signal.score).toFixed(2)} · {String(signal.direction)}</span></div>)}<p class="method-note">{String(evaluation.interpretation)}</p></> : <p class="muted">选择 Thesis 查看当前状态与证据线索。</p>}</Panel>
    </div>
  </div>;
}

