import { Panel } from '@/components/Panel';
import {
  getMacroApiUrl,
  getMacroSeries,
  getMacroSeriesDetail,
  getMacroSnapshot,
  MacroApiError,
  type MacroDataMode,
  type MacroSeriesDetail,
  type MacroSeriesSummary,
  type MacroSnapshot,
  type MacroState,
} from '@/services/macro-client';
import { formatMacroDate, macroCopy } from './i18n';

const SVG_NS = 'http://www.w3.org/2000/svg';

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function svgEl<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attributes: Record<string, string>,
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function modeClass(mode: MacroDataMode): string {
  return `macro-mode-${mode.toLowerCase()}`;
}

function renderModeBadge(mode: MacroDataMode): HTMLElement {
  return el('span', `macro-mode-badge ${modeClass(mode)}`, mode);
}

abstract class MacroPanel extends Panel {
  private refreshTimer: number | null = null;

  protected constructor(id: string, title: string, className = '') {
    super({
      id,
      title,
      className: `macro-panel ${className}`,
      closable: false,
      collapsible: true,
      trackActivity: false,
    });
  }

  public start(): void {
    void this.refresh();
    this.refreshTimer = window.setInterval(() => void this.refresh(), 30_000);
  }

  protected markMode(mode: MacroDataMode): void {
    if (mode === 'LIVE') this.setDataBadge('live', mode);
    else if (mode === 'EMPTY') this.setDataBadge('unavailable', mode);
    else this.setDataBadge('cached', mode);
  }

  protected showMacroError(error: unknown): void {
    if (this.isAbortError(error)) return;
    const copy = macroCopy();
    const message = error instanceof MacroApiError && error.offline
      ? copy.offline
      : error instanceof Error ? error.message : copy.offline;
    this.showError(message, () => void this.refresh(), 15);
  }

  public abstract refresh(): Promise<void>;

  public override destroy(): void {
    if (this.refreshTimer !== null) window.clearInterval(this.refreshTimer);
    super.destroy();
  }
}

export class MacroWorldStatePanel extends MacroPanel {
  constructor() {
    super('macro-world-state', macroCopy().worldState, 'macro-panel-wide');
  }

  public async refresh(): Promise<void> {
    if (!this.content.childElementCount) this.showLoading(macroCopy().initializing);
    try {
      const snapshot = await getMacroSnapshot({ signal: this.signal });
      this.markMode(snapshot.mode);
      this.render(snapshot);
    } catch (error) {
      this.showMacroError(error);
    }
  }

  private render(snapshot: MacroSnapshot): void {
    const copy = macroCopy();
    const root = el('div', 'macro-state-root');
    const notice = el('div', `macro-mode-notice ${modeClass(snapshot.mode)}`);
    notice.append(
      renderModeBadge(snapshot.mode),
      el(
        'span',
        '',
        snapshot.mode === 'DEMO' ? copy.demoNotice
          : snapshot.mode === 'STALE' ? copy.staleNotice
            : snapshot.mode === 'EMPTY' ? copy.emptyNotice : copy.liveNotice,
      ),
    );
    root.appendChild(notice);

    const grid = el('div', 'macro-state-grid');
    for (const state of snapshot.states) grid.appendChild(this.stateCard(state));
    root.appendChild(grid);
    this.content.replaceChildren(root);
  }

  private stateCard(state: MacroState): HTMLElement {
    const copy = macroCopy();
    const card = el('article', `macro-state-card macro-score-${scoreBand(state.score)}`);
    const header = el('div', 'macro-state-card-header');
    header.append(
      el('h3', '', copy[state.key as keyof typeof copy] as string ?? state.key),
      el('span', 'macro-trend', `${trendArrow(state.trend)} ${copy[state.trend]}`),
    );
    if (state.experimental) header.appendChild(el('span', 'macro-tag', copy.experimental));
    card.appendChild(header);

    const score = el(
      'div',
      'macro-state-score',
      state.score === null ? '—' : state.score.toFixed(2),
    );
    const label = el(
      'span',
      'macro-state-label',
      copy[state.label as keyof typeof copy] as string ?? state.label,
    );
    score.appendChild(label);
    card.appendChild(score);

    const confidence = el('div', 'macro-confidence');
    const confidenceLabel = el(
      'span',
      '',
      `${copy.confidence} ${Math.round(state.confidence * 100)}%`,
    );
    if (state.confidence < 0.35) confidenceLabel.append(` · ${copy.lowConfidence}`);
    const meter = el('span', 'macro-confidence-track');
    const fill = el('span', 'macro-confidence-fill');
    fill.style.width = `${Math.round(state.confidence * 100)}%`;
    meter.appendChild(fill);
    confidence.append(confidenceLabel, meter);
    card.appendChild(confidence);

    const driverTitle = el('div', 'macro-small-label', copy.drivers);
    const drivers = el('ul', 'macro-driver-list');
    for (const driver of state.top_drivers.slice(0, 2)) {
      drivers.appendChild(
        el(
          'li',
          '',
          `${driver.title}: ${driver.score >= 0 ? '+' : ''}${driver.score.toFixed(2)}`,
        ),
      );
    }
    if (!state.top_drivers.length) drivers.appendChild(el('li', '', copy.insufficient));
    card.append(driverTitle, drivers);

    const footer = el('div', 'macro-state-footer');
    footer.appendChild(el('span', '', `${copy.updated}: ${formatMacroDate(state.as_of)}`));
    if (state.missing_series.length) {
      footer.appendChild(
        el('span', 'macro-missing', `${copy.missing}: ${state.missing_series.length}`),
      );
    }
    card.appendChild(footer);
    return card;
  }
}

export class MacroChangesPanel extends MacroPanel {
  constructor() {
    super('macro-top-changes', macroCopy().topChanges);
  }

  public async refresh(): Promise<void> {
    if (!this.content.childElementCount) this.showLoading();
    try {
      const snapshot = await getMacroSnapshot({ signal: this.signal });
      this.markMode(snapshot.mode);
      const copy = macroCopy();
      const root = el('div', 'macro-changes');
      if (!snapshot.top_changes.length) {
        root.appendChild(el('div', 'macro-empty', copy.noChanges));
      }
      for (const change of snapshot.top_changes) {
        const item = el('article', `macro-change macro-importance-${change.importance}`);
        const heading = el('div', 'macro-change-heading');
        heading.append(
          el('span', 'macro-change-type', change.type.replace(/_/g, ' ')),
          el('time', '', formatMacroDate(change.date)),
        );
        item.append(
          heading,
          el('h3', '', change.title),
          el('p', '', change.explanation),
          el('div', 'macro-change-source', `${copy.source}: ${change.source}`),
        );
        root.appendChild(item);
      }
      if (snapshot.releases.length) {
        root.appendChild(el('h3', 'macro-section-title', copy.releases));
        for (const release of snapshot.releases) {
          const row = el('div', 'macro-release');
          row.append(
            el('span', '', release.title),
            el('time', '', formatMacroDate(release.scheduled_at, true)),
          );
          root.appendChild(row);
        }
      }
      this.content.replaceChildren(root);
    } catch (error) {
      this.showMacroError(error);
    }
  }
}

export class MacroRegimePanel extends MacroPanel {
  constructor() {
    super('macro-regime', macroCopy().regime);
  }

  public async refresh(): Promise<void> {
    if (!this.content.childElementCount) this.showLoading();
    try {
      const snapshot = await getMacroSnapshot({ signal: this.signal });
      this.markMode(snapshot.mode);
      this.content.replaceChildren(this.renderChart(snapshot));
    } catch (error) {
      this.showMacroError(error);
    }
  }

  private renderChart(snapshot: MacroSnapshot): HTMLElement {
    const copy = macroCopy();
    const wrapper = el('div', 'macro-regime');
    const svg = svgEl('svg', {
      viewBox: '0 0 420 300',
      role: 'img',
      'aria-label': copy.regime,
      class: 'macro-regime-chart',
    });
    svg.append(
      svgEl('rect', { x: '40', y: '20', width: '340', height: '240', class: 'macro-chart-bg' }),
      svgEl('line', { x1: '210', y1: '20', x2: '210', y2: '260', class: 'macro-axis' }),
      svgEl('line', { x1: '40', y1: '140', x2: '380', y2: '140', class: 'macro-axis' }),
    );
    const labels = [
      [copy.quadrants[2], 50, 38],
      [copy.quadrants[1], 292, 38],
      [copy.quadrants[3], 50, 250],
      [copy.quadrants[0], 292, 250],
    ] as const;
    for (const [label, x, y] of labels) {
      const text = svgEl('text', { x: String(x), y: String(y), class: 'macro-quadrant-label' });
      text.textContent = label ?? '';
      svg.appendChild(text);
    }

    const points = snapshot.regime.trajectory.map((point) => ({
      x: 210 + point.growth * 150,
      y: 140 - point.inflation * 105,
    }));
    if (points.length > 1) {
      svg.appendChild(
        svgEl('polyline', {
          points: points.map((point) => `${point.x},${point.y}`).join(' '),
          class: 'macro-trajectory',
        }),
      );
    }
    points.forEach((point, index) => {
      svg.appendChild(
        svgEl('circle', {
          cx: String(point.x),
          cy: String(point.y),
          r: index === points.length - 1 ? '7' : '3',
          class: index === points.length - 1 ? 'macro-current-point' : 'macro-history-point',
        }),
      );
    });
    wrapper.appendChild(svg);
    const legend = el('div', 'macro-regime-legend');
    legend.append(
      el('span', '', `${copy.growth}: ${formatScore(snapshot.regime.growth)}`),
      el('span', '', `${copy.inflation}: ${formatScore(snapshot.regime.inflation)}`),
      el('span', '', `${copy.confidence}: ${Math.round(snapshot.regime.confidence * 100)}%`),
    );
    wrapper.appendChild(legend);
    return wrapper;
  }
}

export class MacroSeriesExplorerPanel extends MacroPanel {
  private catalog: MacroSeriesSummary[] = [];
  private selected = 'US.INFLATION.CPI_HEADLINE';
  private transform = 'level';

  constructor() {
    super('macro-series-explorer', macroCopy().seriesExplorer, 'macro-panel-wide');
  }

  public async refresh(): Promise<void> {
    if (!this.content.childElementCount) this.showLoading();
    try {
      if (!this.catalog.length) this.catalog = await getMacroSeries(this.signal);
      if (!this.catalog.some((item) => item.canonical_key === this.selected)) {
        this.selected = this.catalog[0]?.canonical_key ?? '';
      }
      if (!this.selected) {
        this.content.replaceChildren(el('div', 'macro-empty', macroCopy().insufficient));
        return;
      }
      const [detail, snapshot] = await Promise.all([
        getMacroSeriesDetail(this.selected, this.transform, this.signal),
        getMacroSnapshot({ signal: this.signal }),
      ]);
      this.markMode(snapshot.mode);
      this.render(detail);
    } catch (error) {
      this.showMacroError(error);
    }
  }

  private render(detail: MacroSeriesDetail): void {
    const copy = macroCopy();
    const root = el('div', 'macro-series-root');
    const controls = el('div', 'macro-series-controls');
    const seriesSelect = el('select', 'macro-select');
    seriesSelect.setAttribute('aria-label', copy.seriesExplorer);
    for (const item of this.catalog) {
      const option = el('option', '', `${item.native_id} · ${item.title}`);
      option.value = item.canonical_key;
      option.selected = item.canonical_key === this.selected;
      seriesSelect.appendChild(option);
    }
    const transformSelect = el('select', 'macro-select');
    const transforms = [
      ['level', copy.raw],
      ['yoy', copy.yoy],
      ['rolling_percentile', copy.percentile],
    ] as const;
    for (const [value, label] of transforms) {
      const option = el('option', '', label);
      option.value = value;
      option.selected = value === this.transform;
      transformSelect.appendChild(option);
    }
    seriesSelect.addEventListener('change', () => {
      this.selected = seriesSelect.value;
      void this.refresh();
    });
    transformSelect.addEventListener('change', () => {
      this.transform = transformSelect.value;
      void this.refresh();
    });
    controls.append(seriesSelect, transformSelect);
    root.appendChild(controls);

    root.appendChild(renderSeriesChart(detail));
    const latest = [...detail.observations].reverse().find((item) => item.value !== null);
    const metadata = el('div', 'macro-series-meta');
    const source = el('a', '', `${copy.source}: FRED · ${detail.native_id}`);
    source.href = detail.source_url;
    source.target = '_blank';
    source.rel = 'noreferrer';
    metadata.append(
      el('span', '', `${copy.updated}: ${formatMacroDate(detail.last_updated, true)}`),
      el('span', '', `${copy.revisions}: ${detail.revision_count}`),
      el(
        'span',
        '',
        `${copy.latestPercentile}: ${
          latest?.percentile === null || latest?.percentile === undefined
            ? '—' : `${Math.round(latest.percentile * 100)}%`
        }`,
      ),
      source,
    );
    root.appendChild(metadata);
    this.content.replaceChildren(root);
  }
}

export class MacroSystemStatusPanel extends MacroPanel {
  constructor() {
    super('macro-system-status', macroCopy().systemStatus);
  }

  public async refresh(): Promise<void> {
    if (!this.content.childElementCount) this.showLoading();
    try {
      const snapshot = await getMacroSnapshot({ signal: this.signal });
      this.markMode(snapshot.mode);
      const copy = macroCopy();
      const status = snapshot.system;
      const root = el('div', 'macro-status-list');
      root.append(
        statusRow(copy.engine, copy.online, 'ok'),
        statusRow(copy.database, status.database.toUpperCase()),
        statusRow(
          copy.fred,
          status.fred_configured ? copy.configured : copy.notConfigured,
          status.fred_configured ? 'ok' : 'warn',
        ),
        statusRow(copy.lastSync, formatMacroDate(status.last_sync_at, true)),
        statusRow(copy.syncing, status.syncing ? copy.syncing : '—', status.syncing ? 'warn' : ''),
        statusRow(copy.series, status.series.toLocaleString()),
        statusRow(copy.observations, status.observations.toLocaleString()),
        statusRow('API', getMacroApiUrl()),
        statusRow('Mode', status.mode, status.mode === 'LIVE' ? 'ok' : 'warn'),
      );
      this.content.replaceChildren(root);
    } catch (error) {
      this.showMacroError(error);
    }
  }
}

function statusRow(label: string, value: string, status = ''): HTMLElement {
  const row = el('div', 'macro-status-row');
  row.append(el('span', '', label), el('strong', status, value));
  return row;
}

function renderSeriesChart(detail: MacroSeriesDetail): SVGSVGElement {
  const svg = svgEl('svg', {
    viewBox: '0 0 760 260',
    role: 'img',
    'aria-label': detail.title,
    class: 'macro-series-chart',
  });
  svg.appendChild(
    svgEl('rect', { x: '35', y: '15', width: '705', height: '210', class: 'macro-chart-bg' }),
  );
  const observations = detail.observations
    .filter((item): item is typeof item & { value: number } => item.value !== null)
    .slice(-180);
  if (observations.length < 2) {
    const text = svgEl('text', { x: '380', y: '130', class: 'macro-no-chart' });
    text.textContent = macroCopy().insufficient;
    svg.appendChild(text);
    return svg;
  }
  const values = observations.map((item) => item.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = observations.map((item, index) => {
    const x = 35 + (index / (observations.length - 1)) * 705;
    const y = 225 - ((item.value - min) / range) * 195;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  svg.append(
    svgEl('polyline', { points: points.join(' '), class: 'macro-series-line' }),
    svgEl('line', { x1: '35', y1: '225', x2: '740', y2: '225', class: 'macro-axis' }),
  );
  const maxLabel = svgEl('text', { x: '38', y: '30', class: 'macro-chart-value' });
  maxLabel.textContent = max.toFixed(2);
  const minLabel = svgEl('text', { x: '38', y: '220', class: 'macro-chart-value' });
  minLabel.textContent = min.toFixed(2);
  svg.append(maxLabel, minLabel);
  return svg;
}

function trendArrow(trend: MacroState['trend']): string {
  return trend === 'rising' ? '↑' : trend === 'falling' ? '↓' : '→';
}

function scoreBand(score: number | null): string {
  if (score === null) return 'none';
  if (score > 0.35) return 'positive';
  if (score < -0.35) return 'negative';
  return 'neutral';
}

function formatScore(value: number | null): string {
  return value === null ? '—' : value.toFixed(2);
}
