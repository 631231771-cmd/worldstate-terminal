import { useMemo, useState } from "preact/hooks";
import { Badge, Panel } from "../../components/Primitives";
import type { ReleaseSummary, ViewKey } from "../../types";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "US_CPI", label: "通胀" },
  { key: "US_NFP", label: "就业" },
  { key: "FOMC", label: "央行" },
];

function statusTone(status: string) {
  if (status === "completed") return "good" as const;
  if (status === "pending" || status === "scheduled") return "info" as const;
  return "warn" as const;
}

export function ReleasesWorkspace({
  releases,
  onOpen,
}: {
  releases: ReleaseSummary[];
  onOpen: (releaseId: string, destination?: ViewKey) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const visible = useMemo(
    () => releases.filter((release) =>
      (filter === "all" || release.release_type === filter) &&
      `${release.title} ${release.period_label} ${release.classification}`.toLowerCase().includes(query.toLowerCase()),
    ),
    [filter, query, releases],
  );

  return (
    <div class="workspace">
      <section class="page-heading">
        <div>
          <div class="eyebrow">POINT-IN-TIME RELEASES</div>
          <h1>宏观发布</h1>
          <p>这里是发布档案，不是完成研究的排行榜。共识、行情或分析缺失时会明确显示。</p>
        </div>
      </section>
      <Panel title="发布档案" eyebrow={`${visible.length} RELEASES`}>
        <div class="toolbar">
          <div class="segmented">
            {FILTERS.map((item) => (
              <button type="button" class={filter === item.key ? "active" : ""} onClick={() => setFilter(item.key)} key={item.key}>
                {item.label}
              </button>
            ))}
          </div>
          <input class="search-input" type="search" placeholder="搜索事件、时期或分类" value={query} onInput={(event) => setQuery((event.currentTarget as HTMLInputElement).value)} />
        </div>
        <div class="table-wrap">
          <table class="release-table">
            <thead><tr><th>发布时间</th><th>事件</th><th>综合预期差</th><th>惊喜分数</th><th>污染</th><th>数据模式</th><th>分析状态</th></tr></thead>
            <tbody>
              {visible.map((release) => (
                <tr key={release.id} onClick={() => onOpen(release.id)}>
                  <td><time>{new Date(release.scheduled_at).toLocaleString("zh-CN")}</time><span>{release.status === "scheduled" ? "尚未发布" : release.released_at ? "已发布" : "未确认发布时间"}</span></td>
                  <td><strong>{release.title}</strong><span>{release.release_type} · {release.period_label}</span></td>
                  <td>{release.classification ?? "—"}</td>
                  <td class={Number(release.surprise_score) > 0 ? "negative" : "positive"}>{release.surprise_score?.toFixed(2) ?? "—"}</td>
                  <td><Badge tone={release.clean_window ? "good" : "bad"}>{release.clean_window ? "清洁窗口" : release.contamination_level}</Badge></td>
                  <td>{release.data_mode === "fixture" ? <Badge tone="warn">FIXTURE</Badge> : <Badge tone="info">{release.data_mode}</Badge>}</td>
                  <td>
                    <Badge tone={statusTone(release.analysis_status)}>{release.analysis_status}</Badge>
                    {release.reproducibility_status && release.reproducibility_status !== "complete" ? <span class="muted">不可复现</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
