import { useMemo, useState } from "preact/hooks";
import { Badge, Panel } from "../../components/Primitives";
import type { ReleaseSummary, ViewKey } from "../../types";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "US_CPI", label: "通胀" },
  { key: "US_NFP", label: "就业" },
  { key: "FOMC", label: "央行" },
];

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
    () =>
      releases.filter(
        (release) =>
          (filter === "all" || release.release_type === filter) &&
          `${release.title} ${release.period_label} ${release.classification}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [filter, query, releases],
  );

  return (
    <div class="workspace">
      <section class="page-heading">
        <div>
          <div class="eyebrow">POINT-IN-TIME RELEASES</div>
          <h1>宏观发布</h1>
          <p>每一行是一场有版本、有事前共识、有来源、可重新分析的正式发布。</p>
        </div>
      </section>
      <Panel title="发布档案" eyebrow={`${visible.length} RELEASES`}>
        <div class="toolbar">
          <div class="segmented">
            {FILTERS.map((item) => (
              <button
                type="button"
                class={filter === item.key ? "active" : ""}
                onClick={() => setFilter(item.key)}
                key={item.key}
              >
                {item.label}
              </button>
            ))}
          </div>
          <input
            class="search-input"
            type="search"
            placeholder="搜索事件、时期或分类"
            value={query}
            onInput={(event) => setQuery((event.currentTarget as HTMLInputElement).value)}
          />
        </div>
        <div class="table-wrap">
          <table class="release-table">
            <thead>
              <tr>
                <th>公布时间</th>
                <th>事件</th>
                <th>综合预期差</th>
                <th>惊喜分数</th>
                <th>污染</th>
                <th>质量</th>
                <th>分析</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((release) => (
                <tr key={release.id} onClick={() => onOpen(release.id)}>
                  <td>
                    <time>{new Date(release.scheduled_at).toLocaleString("zh-CN")}</time>
                  </td>
                  <td>
                    <strong>{release.title}</strong>
                    <span>{release.release_type} · {release.period_label}</span>
                  </td>
                  <td>{release.classification ?? "—"}</td>
                  <td class={Number(release.surprise_score) > 0 ? "negative" : "positive"}>
                    {release.surprise_score?.toFixed(2) ?? "—"}
                  </td>
                  <td>
                    <Badge tone={release.clean_window ? "good" : "bad"}>
                      {release.clean_window ? "清洁窗口" : release.contamination_level}
                    </Badge>
                  </td>
                  <td>
                    {release.data_mode === "fixture" ? (
                      <Badge tone="warn">FIXTURE</Badge>
                    ) : (
                      <Badge tone="info">{release.data_mode}</Badge>
                    )}
                  </td>
                  <td><Badge tone="good">{release.analysis_status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
