import { initI18n } from '@/services/i18n';
import {
  askWorldTutor,
  getWorldBriefing,
  MacroApiError,
  type TutorAnswer,
  type TutorMessage,
  type TutorMode,
  type WorldBriefing,
  type WorldEvent,
  type WorldMarket,
} from '@/services/macro-client';
import { registerWorldStateTools } from './webmcp';
import './macro-terminal.css';

const SVG_NS = 'http://www.w3.org/2000/svg';
type WorldView =
  | 'overview'
  | 'events'
  | 'calendar'
  | 'markets'
  | 'themes'
  | 'signals'
  | 'library';

const WORLD_VIEWS: ReadonlyArray<{
  key: WorldView;
  label: string;
  shortLabel: string;
}> = [
  { key: 'overview', label: '今日桌面', shortLabel: '今日' },
  { key: 'events', label: '事件雷达', shortLabel: '事件' },
  { key: 'calendar', label: '宏观日历', shortLabel: '日历' },
  { key: 'markets', label: '资产地图', shortLabel: '市场' },
  { key: 'themes', label: '国家与主题', shortLabel: '主题' },
  { key: 'signals', label: '观点与证据', shortLabel: '证据' },
  { key: 'library', label: '学习与复盘', shortLabel: '学习' },
];

interface TutorEntry extends TutorMessage {
  provider?: string;
  citations?: TutorAnswer['citations'];
}

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

function externalLink(label: string, url: string, className = ''): HTMLAnchorElement {
  const anchor = el('a', className, label);
  anchor.href = url;
  anchor.target = '_blank';
  anchor.rel = 'noreferrer';
  return anchor;
}

function formatDate(value: string | null | undefined, includeTime = true): string {
  if (!value) return '时间待确认';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(document.documentElement.lang.startsWith('zh') ? 'zh-CN' : 'en', {
    timeZone: 'Asia/Taipei',
    month: 'short',
    day: 'numeric',
    hour: includeTime ? '2-digit' : undefined,
    minute: includeTime ? '2-digit' : undefined,
    hour12: false,
  }).format(parsed);
}

function formatPrice(market: WorldMarket): string {
  if (!market.available || market.price === undefined) return '—';
  const digits = market.price >= 1000 ? 0 : market.price >= 10 ? 2 : 3;
  return market.price.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatMove(value: number | null | undefined, fallback = '待更新'): string {
  if (value === null || value === undefined) return fallback;
  const normalized = Math.abs(value) < 0.005 ? 0 : value;
  return `${normalized > 0 ? '+' : ''}${normalized.toFixed(2)}%`;
}

function renderSparkline(values: number[] | undefined, direction: WorldMarket['direction']): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 140 40');
  svg.setAttribute('class', `world-sparkline world-sparkline-${direction}`);
  svg.setAttribute('aria-hidden', 'true');
  if (!values || values.length < 2) return svg;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * 138 + 1;
    const y = 37 - ((value - min) / range) * 34;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = document.createElementNS(SVG_NS, 'polyline');
  line.setAttribute('points', points.join(' '));
  svg.appendChild(line);
  return svg;
}

function readWorldView(): WorldView {
  const candidate = new URL(window.location.href).searchParams.get('view');
  return WORLD_VIEWS.some((view) => view.key === candidate) ? candidate as WorldView : 'overview';
}

export class MacroApp {
  private readonly root: HTMLElement;
  private controller: AbortController | null = null;
  private briefing: WorldBriefing | null = null;
  private tutorMode: TutorMode = 'beginner';
  private tutorEntries: TutorEntry[] = [];
  private tutorBusy = false;
  private refreshTimer: number | null = null;
  private currentView: WorldView = readWorldView();
  private readonly handlePopState = (): void => {
    this.currentView = readWorldView();
    this.render();
  };

  constructor(rootId: string) {
    const root = document.getElementById(rootId);
    if (!root) throw new Error(`Missing application root #${rootId}`);
    this.root = root;
    this.prepareDocument();
    window.addEventListener('popstate', this.handlePopState);
  }

  public async init(): Promise<void> {
    this.applyDefaultLanguage();
    await initI18n();
    document.title = '世界状态终端 · 每日世界解释';
    this.renderLoading();
    await this.refresh(false);
    this.refreshTimer = window.setInterval(() => void this.refresh(false), 5 * 60_000);
  }

  private prepareDocument(): void {
    document.documentElement.classList.add('js', 'world-macro-active');
    const prerender = document.getElementById('seo-prerender');
    if (prerender) prerender.hidden = true;
    const crawlerHeading = document.querySelector<HTMLElement>('body > .app-heading');
    if (crawlerHeading) crawlerHeading.hidden = true;
  }

  private applyDefaultLanguage(): void {
    const url = new URL(window.location.href);
    if (!url.searchParams.has('lang')) {
      url.searchParams.set('lang', 'zh');
      history.replaceState(history.state, '', url);
    }
  }

  private renderLoading(): void {
    const shell = el('main', 'world-shell');
    const loading = el('section', 'world-loading');
    loading.append(
      el('div', 'world-loading-orbit'),
      el('h1', '', '正在连接今天的世界'),
      el('p', '', '汇集公开新闻、全球市场与宏观证据…'),
    );
    shell.appendChild(loading);
    this.root.replaceChildren(shell);
  }

  private async refresh(fresh: boolean): Promise<void> {
    this.controller?.abort();
    this.controller = new AbortController();
    try {
      this.briefing = await getWorldBriefing({ signal: this.controller.signal, fresh });
      this.render();
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      this.renderError(error);
    }
  }

  private renderError(error: unknown): void {
    const offline = error instanceof MacroApiError && error.offline;
    const shell = el('main', 'world-shell');
    const card = el('section', 'world-error');
    card.append(
      el('div', 'world-kicker', 'WORLD STATE / CONNECTION'),
      el('h1', '', offline ? '世界解释引擎尚未启动' : '暂时无法生成今日简报'),
      el(
        'p',
        '',
        offline
          ? '请双击桌面的“打开世界状态终端.bat”，等待浏览器自动打开。'
          : error instanceof Error ? error.message : '免费数据源暂时不可用。',
      ),
    );
    const retry = el('button', 'world-primary-button', '重新连接');
    retry.type = 'button';
    retry.addEventListener('click', () => {
      this.renderLoading();
      void this.refresh(true);
    });
    card.appendChild(retry);
    shell.appendChild(card);
    this.root.replaceChildren(shell);
  }

  private render(): void {
    if (!this.briefing) return;
    const shell = el('main', 'world-shell');
    shell.append(this.renderHeader(), this.renderMarketTicker());

    const workspace = el('div', `world-workspace world-workspace-${this.currentView}`);
    const editorial = el('div', 'world-editorial-column');
    editorial.appendChild(this.renderCurrentView());
    workspace.append(editorial, this.renderTutor());
    shell.appendChild(workspace);
    shell.appendChild(this.renderFooter());
    this.root.replaceChildren(shell);
    registerWorldStateTools(this.briefing);
  }

  private renderHeader(): HTMLElement {
    const briefing = this.briefing!;
    const header = el('header', 'world-topbar');
    const brand = el('div', 'world-brand');
    brand.append(
      el('span', 'world-brand-mark', 'WST'),
      el('div', 'world-brand-copy', '世界状态终端'),
    );
    const nav = el('nav', 'world-nav');
    nav.setAttribute('aria-label', '页面导航');
    for (const item of WORLD_VIEWS) {
      const link = el('a', item.key === this.currentView ? 'is-active' : '', item.label);
      const url = new URL(window.location.href);
      url.searchParams.set('view', item.key);
      link.href = url.toString();
      if (item.key === this.currentView) link.setAttribute('aria-current', 'page');
      link.addEventListener('click', (event) => {
        event.preventDefault();
        this.navigate(item.key);
      });
      nav.appendChild(link);
    }
    const meta = el('div', 'world-topbar-meta');
    const mode = el(
      'span',
      `world-evidence-mode world-evidence-${briefing.evidence_mode.toLowerCase()}`,
      briefing.evidence_mode === 'LIVE'
        ? '公开证据在线'
        : briefing.evidence_mode === 'PARTIAL' ? '部分证据' : '离线模式',
    );
    const updated = el('span', 'world-updated', `更新于 ${formatDate(briefing.generated_at)}`);
    const refresh = el('button', 'world-icon-button', '刷新');
    refresh.type = 'button';
    refresh.addEventListener('click', () => void this.refresh(true));
    const language = el('button', 'world-icon-button', '中 / EN');
    language.type = 'button';
    language.addEventListener('click', () => {
      const url = new URL(window.location.href);
      url.searchParams.set('lang', document.documentElement.lang.startsWith('zh') ? 'en' : 'zh');
      window.location.href = url.toString();
    });
    meta.append(mode, updated, refresh, language);
    header.append(brand, nav, meta);
    return header;
  }

  private navigate(
    view: WorldView,
    selection: { event?: string; market?: string; release?: string; topic?: string } = {},
  ): void {
    const url = new URL(window.location.href);
    url.searchParams.set('view', view);
    if (selection.event) url.searchParams.set('event', selection.event);
    else if (view !== 'events') url.searchParams.delete('event');
    if (selection.market) url.searchParams.set('market', selection.market);
    else if (view !== 'markets') url.searchParams.delete('market');
    if (selection.release) url.searchParams.set('release', selection.release);
    else if (view !== 'calendar') url.searchParams.delete('release');
    if (selection.topic) url.searchParams.set('topic', selection.topic);
    else if (view !== 'themes') url.searchParams.delete('topic');
    history.pushState({ view }, '', url);
    this.currentView = view;
    this.render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  private renderCurrentView(): HTMLElement {
    const page = el('div', `world-view world-view-${this.currentView}`);
    if (this.currentView === 'events') {
      page.append(this.renderViewHeading(
        'EVENT RADAR',
        '事件雷达与完整传导',
        '从事实、预期差、传导机制到跨资产验证，把一条新闻真正理解清楚。',
      ), this.renderEventResearch());
      return page;
    }
    if (this.currentView === 'markets') {
      page.append(this.renderViewHeading(
        'CROSS-ASSET MAP',
        '资产地图与跨市场验证',
        '同时看方向、期限、广度、相关性与背离，再讨论今天的涨跌为什么重要。',
      ), this.renderMarketResearch());
      return page;
    }
    if (this.currentView === 'calendar') {
      page.append(this.renderViewHeading(
        'EVENT STUDY DESK',
        '事件研究工作台',
        '从刚刚发生的事件出发，沿“预期差 → 定价变量 → 资产分化 → 杠杆放大 → 后续验证”完成一次复盘。',
      ), this.renderCalendarWorkspace());
      return page;
    }
    if (this.currentView === 'themes') {
      page.append(this.renderViewHeading(
        'COUNTRY & THEME MAP',
        '国家、区域与宏观主题',
        '把每天分散的新闻重新组织到利率、通胀、增长、流动性、能源、贸易和亚洲周期中。',
      ), this.renderThemeWorkspace());
      return page;
    }
    if (this.currentView === 'signals') {
      page.append(this.renderViewHeading(
        'VIEWPOINT & EVIDENCE',
        '观点、证据与调用透明度',
        '看到观点，也看到它与今日主线是否相关、从哪里来、调用是否成功、应该怎样验证。',
      ), this.renderPipeline(), this.renderIntegrationConsole(), this.renderPerspectives(), this.renderSourceWorkbench());
      return page;
    }
    if (this.currentView === 'library') {
      page.append(this.renderViewHeading(
        'LEARNING & REVIEW',
        '学习、事件模板与复盘',
        '把今天的事件放进可重复使用的宏观模板，再按问题补概念、看原始资料。',
      ), this.renderLesson(), this.renderEventArchetypes(), this.renderCurriculum(), this.renderMacroFoundation(), this.renderMethodLibrary());
      return page;
    }
    page.append(
      this.renderHero(),
      this.renderCommandDesk(),
      this.renderRegimeBoard(),
      this.renderCrossAssetPatterns(),
      this.renderEvents(5),
      this.renderTopicMap(true),
      this.renderPipeline(true),
    );
    return page;
  }

  private renderViewHeading(kicker: string, title: string, description: string): HTMLElement {
    const heading = el('section', 'world-view-heading');
    heading.append(
      el('div', 'world-kicker', kicker),
      el('h1', '', title),
      el('p', '', description),
    );
    return heading;
  }

  private renderMarketTicker(): HTMLElement {
    const ticker = el('section', 'world-ticker');
    ticker.setAttribute('aria-label', '全球市场速览');
    for (const market of this.briefing!.markets) {
      const item = el('div', `world-ticker-item world-move-${market.direction}`);
      const change =
        formatMove(market.change_percent);
      item.append(
        el('span', 'world-ticker-name', market.name_zh),
        el('strong', '', formatPrice(market)),
        el('span', 'world-ticker-change', change),
      );
      ticker.appendChild(item);
    }
    return ticker;
  }

  private renderHero(): HTMLElement {
    const briefing = this.briefing!;
    const lead = briefing.events[0];
    const hero = el('section', 'world-hero');
    hero.id = 'today';
    const copy = el('div', 'world-hero-copy');
    copy.append(
      el('div', 'world-kicker', `DAILY WORLD BRIEF · ${formatDate(briefing.generated_at, false)}`),
      el('h1', '', briefing.headline),
      el('p', 'world-mission', briefing.mission),
    );
    if (lead) {
      const question = el('div', 'world-core-question');
      question.append(el('span', '', '今日核心问题'), el('strong', '', lead.core_question));
      copy.appendChild(question);
    }

    const focus = el('article', 'world-focus-card');
    focus.append(
      el('div', 'world-focus-header', '先形成假设，再让价格检验'),
      el('h2', '', lead?.scenario ?? '等待公开证据形成今日主线'),
    );
    if (lead) {
      const chain = el('ol', 'world-focus-chain');
      lead.causal_chain.slice(0, 4).forEach((step, index) => {
        const item = el('li');
        const content = el('div');
        content.append(
          el('small', '', lead.chain_labels[index] ?? `步骤 ${index + 1}`),
          el('p', '', step),
        );
        item.append(el('span', '', String(index + 1)), content);
        chain.appendChild(item);
      });
      focus.append(chain, el('p', 'world-focus-note', `待验证：${lead.expectation_shift}`));
    } else {
      focus.appendChild(el('p', 'world-focus-note', '新闻与价格都不足时，不强行生成因果故事。'));
    }
    hero.append(copy, focus);
    return hero;
  }

  private renderCommandDesk(): HTMLElement {
    const briefing = this.briefing!;
    const lead = briefing.events[0];
    const nextRelease = briefing.desk.next_high_impact;
    const section = el('section', 'world-command-desk');
    section.id = 'desk';

    const metrics = el('div', 'world-desk-metrics');
    [
      ['事件雷达', `${briefing.desk.event_count} 条`],
      ['市场覆盖', briefing.desk.market_coverage],
      ['证据来源', `${briefing.desk.source_count} 组`],
      ['活跃主题', `${briefing.desk.active_topics.length} 个`],
    ].forEach(([label, value]) => {
      const item = el('div');
      item.append(el('span', '', label), el('strong', '', value));
      metrics.appendChild(item);
    });

    const leadCard = el('article', 'world-desk-lead');
    leadCard.append(
      el('span', 'world-mini-label', 'TODAY / 主线判断'),
      el('h2', '', briefing.desk.question),
      el('p', '', lead?.why_it_matters ?? '当前没有足够证据形成主线，等待下一项可核对信息。'),
    );
    if (lead) {
      const actions = el('div', 'world-card-actions');
      const research = el('button', 'world-primary-button', '打开完整传导链');
      research.type = 'button';
      research.addEventListener('click', () => this.navigate('events', { event: lead.id }));
      const ask = el('button', 'world-secondary-button', '让 AI 用初学者方式解释');
      ask.type = 'button';
      ask.addEventListener('click', () => void this.askTutor(`请用初学者能听懂的方式解释：${lead.core_question}`));
      actions.append(research, ask);
      leadCard.appendChild(actions);
    }

    const releaseCard = el('article', 'world-desk-release');
    releaseCard.append(el('span', 'world-mini-label', 'NEXT / 下一项高影响日程'));
    if (nextRelease) {
      releaseCard.append(
        el('time', '', formatDate(nextRelease.scheduled_at)),
        el('h3', '', nextRelease.title),
        el('p', '', nextRelease.question),
      );
      const button = el('button', 'world-text-button', '打开事件预案 →');
      button.type = 'button';
      button.addEventListener('click', () => this.navigate('calendar', { release: nextRelease.id }));
      releaseCard.appendChild(button);
    } else {
      releaseCard.append(el('h3', '', '官方日程等待更新'), el('p', '', '不会用未经核对的日期填充日历。'));
    }
    section.append(metrics, this.renderReactionWorkbench(true), leadCard, releaseCard);
    return section;
  }

  private renderRegimeBoard(): HTMLElement {
    const system = this.briefing!.market_system;
    const section = el('section', 'world-section world-regime-board');
    section.id = 'regimes';
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(
      el('div', 'world-section-index', 'MARKET-IMPLIED REGIME'),
      el('h2', '', '市场现在共同在定价什么'),
      el('p', '', '这是由跨资产方向推断的“市场状态”，不是对经济数据的预测。'),
    );
    const breadth = el(
      'div',
      'world-breadth',
      `${system.breadth.up} 涨 · ${system.breadth.down} 跌 · ${system.breadth.flat} 平`,
    );
    heading.append(title, breadth);
    section.appendChild(heading);
    const grid = el('div', 'world-regime-grid');
    system.regimes.forEach((regime) => {
      const card = el('article', `world-regime-card is-${regime.score > 24 ? 'positive' : regime.score < -24 ? 'negative' : 'neutral'}`);
      const top = el('div', 'world-regime-top');
      top.append(el('h3', '', regime.title), el('strong', '', regime.label));
      const meter = el('div', 'world-regime-meter');
      const fill = el('span');
      fill.style.setProperty('--regime-score', `${Math.abs(regime.score)}%`);
      meter.appendChild(fill);
      card.append(top, meter, el('p', '', regime.summary));
      const meta = el('div', 'world-regime-meta');
      meta.append(
        el('span', '', `${regime.score >= 0 ? '+' : ''}${regime.score.toFixed(0)}`),
        el('span', '', `证据置信 ${Math.round(regime.confidence * 100)}%`),
      );
      card.appendChild(meta);
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderCrossAssetPatterns(): HTMLElement {
    const patterns = this.briefing!.market_system.patterns;
    const section = el('section', 'world-section world-patterns');
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', 'CROSS-ASSET CONFIRMATION'),
      el('h2', '', '最值得注意的跨资产共振与背离'),
      el('p', '', '只有多个独立市场共同反应，一条宏观解释才会得到更高权重。'),
    );
    section.appendChild(heading);
    const grid = el('div', 'world-pattern-grid');
    if (!patterns.length) {
      grid.appendChild(el('p', 'world-empty', '当前市场没有形成足够清晰的跨资产组合信号。'));
    }
    patterns.forEach((pattern) => {
      const card = el('article', `world-pattern-card is-${pattern.state}`);
      card.append(
        el('span', 'world-pattern-state', pattern.state.toUpperCase()),
        el('h3', '', pattern.title),
        el('p', '', pattern.explanation),
        el('small', '', `${pattern.markets.join(' · ')} · 置信 ${Math.round(pattern.confidence * 100)}%`),
      );
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderCalendarWorkspace(): HTMLElement {
    const briefing = this.briefing!;
    const releases = briefing.calendar.events;
    const requested = new URL(window.location.href).searchParams.get('release');
    const selected = releases.find((release) => release.id === requested)
      ?? releases.find((release) => release.id === briefing.event_reaction.event_id)
      ?? releases[0];
    const section = el('section', 'world-calendar-workspace');
    section.id = 'calendar';
    section.appendChild(this.renderReactionWorkbench(false));

    const status = el('div', 'world-calendar-status');
    status.append(
      el('strong', '', `${briefing.calendar.status.sources_succeeded}/${briefing.calendar.status.sources_attempted || briefing.calendar.status.sources_succeeded} 个官方日程源可用`),
      el('span', '', `${releases.length} 项近期与未来日程`),
      el('span', '', '官方时间负责“发生了什么”；预期值与价格负责“市场怎样理解”。'),
    );
    section.appendChild(status);

    const browserHeading = el('div', 'world-calendar-browser-heading');
    browserHeading.append(
      el('div', 'world-section-index', 'EVENT BROWSER'),
      el('h2', '', '切换事件，查看事前预案'),
      el('p', '', briefing.calendar.method),
    );
    section.appendChild(browserHeading);

    const layout = el('div', 'world-calendar-layout');
    const list = el('div', 'world-calendar-list');
    let previousDay = '';
    releases.forEach((release) => {
      const day = formatDate(release.scheduled_at, false);
      if (day !== previousDay) {
        list.appendChild(el('div', 'world-calendar-day', day));
        previousDay = day;
      }
      const button = el('button', `world-calendar-row${release.id === selected?.id ? ' is-active' : ''}`);
      button.type = 'button';
      const released = new Date(release.scheduled_at).getTime() <= Date.now();
      button.append(
        el('time', '', formatDate(release.scheduled_at).split(' ').slice(-1)[0] ?? ''),
        el('span', `world-country-code is-${release.country.toLowerCase()}`, release.country),
        el('strong', '', release.title),
        el(
          'span',
          `world-impact is-${released ? 'released' : release.impact}`,
          released ? '已公布' : release.impact === 'high' ? '高影响' : '中影响',
        ),
      );
      button.addEventListener('click', () => this.navigate('calendar', { release: release.id }));
      list.appendChild(button);
    });
    if (!releases.length) list.appendChild(el('p', 'world-empty', '官方日历当前不可用，没有用猜测日期填充。'));

    const detail = el('article', 'world-calendar-detail');
    if (selected) {
      const selectedReleased = new Date(selected.scheduled_at).getTime() <= Date.now();
      detail.append(
        el(
          'span',
          'world-mini-label',
          `${selected.country} / ${selected.kind.toUpperCase()} / ${selectedReleased ? 'RELEASED' : selected.impact.toUpperCase()}`,
        ),
        el('time', 'world-calendar-time', formatDate(selected.scheduled_at)),
        el('h2', '', selected.title),
        el('p', 'world-calendar-question', selected.question),
      );
      const path = el('ol', 'world-release-path');
      [
        ['01', '事实', selectedReleased ? '官方时间已到，先核对原始公布。' : '先记住官方时间与统计口径。'],
        ['02', '预期差', '比较实际值、市场共识与前值修订。'],
        ['03', '变量', '先看利率、美元，再看油价与风险偏好。'],
        ['04', '资产', '同向不等于同因，逐个拆解资产通道。'],
        ['05', '放大', '算法、止损、期权与清算改变速度。'],
        ['06', '验证', '等待第二市场和后续时段确认。'],
      ].forEach(([number, title, copy]) => {
        const item = el('li');
        item.append(
          el('span', '', number),
          el('strong', '', title),
          el('p', '', copy),
        );
        path.appendChild(item);
      });
      detail.appendChild(path);
      const scenarios = el('div', 'world-calendar-scenarios');
      const hotter = el('div', 'is-hotter');
      hotter.append(el('span', '', '如果偏强 / 偏鹰'), el('p', '', selected.scenario_hotter));
      const softer = el('div', 'is-softer');
      softer.append(el('span', '', '如果偏弱 / 偏鸽'), el('p', '', selected.scenario_softer));
      scenarios.append(hotter, softer);
      const watch = el('div', 'world-calendar-watch');
      watch.appendChild(el('span', '', '第一批确认资产'));
      selected.watch_assets.forEach((key) => {
        const market = briefing.markets.find((row) => row.key === key);
        watch.appendChild(el('strong', '', market?.name_zh ?? key));
      });
      const source = selected.source_url
        ? externalLink(`${selected.source} ↗`, selected.source_url, 'world-source-link')
        : el('span', 'world-source-link', selected.source);
      const provenance = el('div', 'world-calendar-provenance');
      provenance.append(
        source,
        el('span', '', selected.retrieval === 'live_official' ? '官方日程实时读取' : '已标注的官方年度日程回退'),
      );
      const ask = el('button', 'world-primary-button', '让 AI 帮我做事件前预演');
      ask.type = 'button';
      ask.textContent = selectedReleased ? '让 AI 帮我复盘这次事件' : '让 AI 帮我做事件前预演';
      ask.addEventListener('click', () => void this.askTutor(
        selectedReleased
          ? `请按“预期差、定价变量、各资产通道、杠杆放大、下一步验证”复盘 ${selected.title}。`
          : `请为 ${selected.title} 做一个事件前预演，说明两种结果如何影响跨资产。`,
      ));
      detail.append(scenarios, watch, provenance, ask);
    } else {
      detail.appendChild(el('p', 'world-empty', '选择一项日程查看预期差与跨资产预案。'));
    }
    layout.append(list, detail);
    section.appendChild(layout);
    return section;
  }

  private renderReactionWorkbench(compact: boolean): HTMLElement {
    const reaction = this.briefing!.event_reaction;
    const section = el(
      'section',
      `world-reaction-workbench${compact ? ' is-compact' : ''} is-${reaction.state}`,
    );
    const header = el('div', 'world-reaction-header');
    const identity = el('div');
    identity.append(
      el('div', 'world-section-index', compact ? 'JUST HAPPENED' : 'LATEST EVENT / REACTION PATH'),
      el('h2', '', compact ? `刚刚发生：${reaction.title}` : reaction.title),
      el(
        'p',
        '',
        reaction.scheduled_at
          ? `${formatDate(reaction.scheduled_at)} · ${reaction.window_label}`
          : reaction.window_label,
      ),
    );
    const badge = el('div', `world-reaction-state is-${reaction.state}`);
    badge.append(
      el('span', '', reaction.state_label),
      el('strong', '', reaction.verdict.label),
      el('small', '', `证据置信 ${reaction.verdict.confidence_label}`),
    );
    header.append(identity, badge);
    section.appendChild(header);

    const flow = el('ol', 'world-reaction-flow');
    reaction.steps.forEach((step) => {
      const item = el('li', `is-${step.state}`);
      item.append(
        el('span', '', step.number),
        el('strong', '', step.title),
        el('p', '', step.summary),
      );
      flow.appendChild(item);
    });
    section.appendChild(flow);

    if (compact) {
      const compactBottom = el('div', 'world-reaction-compact-bottom');
      compactBottom.append(
        el('p', '', reaction.verdict.summary),
        el('strong', '', reaction.shared_move_note),
      );
      const open = el('button', 'world-primary-button', '打开完整事件复盘');
      open.type = 'button';
      open.addEventListener('click', () => this.navigate('calendar', {
        release: reaction.event_id ?? undefined,
      }));
      compactBottom.appendChild(open);
      section.appendChild(compactBottom);
      return section;
    }

    const values = el('div', 'world-reaction-values');
    [
      ['实际值', reaction.values.actual],
      ['市场共识', reaction.values.forecast],
      ['前值 / 修订', reaction.values.previous],
    ].forEach(([label, value]) => {
      const item = el('div');
      item.append(
        el('span', '', String(label)),
        el(
          'strong',
          value === null
            ? reaction.state === 'released' ? '待核验' : '待公布'
            : String(value),
        ),
      );
      values.appendChild(item);
    });
    const valuesNote = el('p', 'world-reaction-values-note', reaction.values.note);
    section.append(values, valuesNote);

    const analysis = el('div', 'world-reaction-analysis');
    const variables = el('section', 'world-reaction-panel world-reaction-variables');
    variables.append(
      el('div', 'world-mini-label', 'FIRST PRICING VARIABLES'),
      el('h3', '', '市场先改了哪几个价格'),
    );
    reaction.pricing_variables.forEach((variable) => {
      const row = el('article', `world-move-${variable.direction}`);
      row.append(
        el('strong', '', variable.name),
        el('span', '', formatMove(variable.move, '待更新')),
        el('p', '', variable.reading),
      );
      variables.appendChild(row);
    });
    if (!reaction.pricing_variables.length) {
      variables.appendChild(el('p', 'world-empty', '当前没有足够价格变量形成确认。'));
    }

    const assets = el('section', 'world-reaction-panel world-reaction-assets');
    assets.append(
      el('div', 'world-mini-label', 'ASSET-SPECIFIC CHANNELS'),
      el('h3', '', '同涨同跌，也可能不是同一个原因'),
    );
    reaction.asset_reactions.forEach((asset) => {
      const row = el('article', `world-move-${asset.direction}`);
      const top = el('div');
      top.append(
        el('strong', '', asset.name),
        el('span', '', formatMove(asset.move, '待更新')),
        el('small', '', asset.role),
      );
      row.append(top, el('p', '', asset.channel));
      assets.appendChild(row);
    });
    assets.appendChild(el('p', 'world-reaction-shared-note', reaction.shared_move_note));
    analysis.append(variables, assets);
    section.appendChild(analysis);

    const reasoning = el('div', 'world-reaction-reasoning');
    const amplifiers = el('section');
    amplifiers.append(
      el('div', 'world-mini-label', 'AMPLIFIERS ≠ ROOT CAUSE'),
      el('h3', '', '什么会把第一轮波动放大'),
    );
    const amplifierList = el('ul');
    reaction.amplifiers.forEach((item) => amplifierList.appendChild(el('li', '', item)));
    amplifiers.appendChild(amplifierList);

    const next = el('section');
    next.append(
      el('div', 'world-mini-label', 'NEXT CHECKS'),
      el('h3', '', '接下来怎样证明或推翻'),
    );
    const nextList = el('ol');
    reaction.next_checks.forEach((item) => nextList.appendChild(el('li', '', item)));
    next.appendChild(nextList);
    reasoning.append(amplifiers, next);
    section.appendChild(reasoning);

    const verdict = el('div', 'world-reaction-verdict');
    verdict.append(
      el('span', '', reaction.verdict.label),
      el('strong', '', reaction.verdict.summary),
      el('small', '', reaction.caveats.join(' · ')),
    );
    if (reaction.source_url) {
      verdict.appendChild(externalLink(`${reaction.source ?? '官方来源'} ↗`, reaction.source_url));
    }
    section.appendChild(verdict);
    return section;
  }

  private renderTopicMap(compact = false): HTMLElement {
    const topics = this.briefing!.topics;
    const section = el('section', `world-section world-topic-map${compact ? ' is-compact' : ''}`);
    section.id = 'topics';
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(
      el('div', 'world-section-index', 'MACRO TOPIC MAP'),
      el('h2', '', '今天的新闻属于哪一条长期宏观线索'),
      el('p', '', '主题强度综合事件重要性、外部观点数量和相关资产波动，不把热度当成事实。'),
    );
    heading.appendChild(title);
    if (compact) {
      const button = el('button', 'world-text-button', '打开完整主题地图 →');
      button.type = 'button';
      button.addEventListener('click', () => this.navigate('themes'));
      heading.appendChild(button);
    }
    section.appendChild(heading);
    const grid = el('div', 'world-topic-grid');
    topics.slice(0, compact ? 6 : topics.length).forEach((topic) => {
      const card = el('article', `world-topic-card is-${topic.state}`);
      const top = el('div');
      top.append(el('span', '', topic.label), el('strong', '', `${Math.round(topic.strength)}`));
      card.append(
        top,
        el('h3', '', topic.title),
        el('p', '', topic.question),
        el('small', '', `${topic.event_count} 个事件 · ${topic.perspective_count} 条观点`),
      );
      const meter = el('div', 'world-topic-meter');
      const fill = el('span');
      fill.style.width = `${Math.max(4, topic.strength)}%`;
      meter.appendChild(fill);
      card.appendChild(meter);
      const button = el('button', 'world-text-button', '查看证据');
      button.type = 'button';
      button.addEventListener('click', () => this.navigate('themes', { topic: topic.key }));
      card.appendChild(button);
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderThemeWorkspace(): HTMLElement {
    const briefing = this.briefing!;
    const requested = new URL(window.location.href).searchParams.get('topic');
    const topic = briefing.topics.find((row) => row.key === requested) ?? briefing.topics[0];
    const wrapper = el('div', 'world-theme-workspace');
    wrapper.appendChild(this.renderTopicMap(false));
    if (topic) {
      const focus = el('section', 'world-theme-focus');
      focus.append(
        el('span', 'world-mini-label', `${topic.label} / 强度 ${Math.round(topic.strength)}`),
        el('h2', '', topic.title),
        el('p', 'world-theme-question', topic.question),
        el('p', '', topic.why_now),
      );
      const evidence = el('div', 'world-theme-evidence');
      topic.market_moves.forEach((move) => {
        const market = briefing.markets.find((row) => row.key === move.key);
        const value = move.change_percent;
        const row = el('div');
        row.append(
          el('span', '', market?.name_zh ?? move.key),
          el('strong', `world-move-${value === null ? 'unavailable' : value > 0 ? 'up' : value < 0 ? 'down' : 'flat'}`, formatMove(value)),
        );
        evidence.appendChild(row);
      });
      const ask = el('button', 'world-secondary-button', '让 AI 串起这条主题链');
      ask.type = 'button';
      ask.addEventListener('click', () => void this.askTutor(`请把今天的“${topic.title}”主题串成完整传导链，并指出证据和反证。`));
      focus.append(evidence, ask);
      wrapper.appendChild(focus);
    }

    const countries = el('section', 'world-section world-country-map');
    countries.appendChild(this.renderViewHeading(
      'REGIONAL ATTENTION',
      '哪些国家和区域需要优先理解',
      '关注度来自新闻与相关市场波动，不代表风险评级，也不比较国家好坏。',
    ));
    const grid = el('div', 'world-country-grid');
    briefing.countries.forEach((country) => {
      const card = el('article', 'world-country-card');
      card.append(
        el('span', 'world-country-flag', country.flag),
        el('div', 'world-country-score', String(Math.round(country.attention))),
        el('h3', '', country.name),
        el('p', '', country.question),
        el('small', '', country.lead),
      );
      const bar = el('div', 'world-country-meter');
      const fill = el('span');
      fill.style.width = `${Math.max(3, country.attention)}%`;
      bar.appendChild(fill);
      card.appendChild(bar);
      grid.appendChild(card);
    });
    countries.appendChild(grid);
    wrapper.appendChild(countries);
    return wrapper;
  }

  private renderPipeline(compact = false): HTMLElement {
    const modules = this.briefing!.research_pipeline;
    const section = el('section', `world-section world-pipeline${compact ? ' is-compact' : ''}`);
    section.id = 'pipeline';
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(
      el('div', 'world-section-index', 'RESEARCH PIPELINE'),
      el('h2', '', '这份解释背后实际调用了什么'),
      el('p', '', '把行情、新闻、观点、X、官方日历、宏观底座与 AI 分开显示，避免“有内容”冒充“有证据”。'),
    );
    heading.appendChild(title);
    if (compact) {
      const button = el('button', 'world-text-button', '查看全部调用 →');
      button.type = 'button';
      button.addEventListener('click', () => this.navigate('signals'));
      heading.appendChild(button);
    }
    section.appendChild(heading);
    const grid = el('div', 'world-pipeline-grid');
    modules.slice(0, compact ? 7 : modules.length).forEach((module) => {
      const card = el('article', `world-pipeline-card is-${module.state}`);
      card.append(
        el('span', 'world-pipeline-state', module.state),
        el('h3', '', module.title),
        el('strong', '', `${module.succeeded}/${module.attempted || module.succeeded} · ${module.items} 项`),
        el('p', '', module.detail),
      );
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderEventArchetypes(): HTMLElement {
    const section = el('section', 'world-section world-archetypes');
    section.id = 'archetypes';
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', 'EVENT PLAYBOOKS'),
      el('h2', '', '六类事件，反复练习同一套判断方法'),
      el('p', '', '用事件模板积累可迁移的直觉：触发器、先行市场、完整路径和失败条件。'),
    );
    section.appendChild(heading);
    const grid = el('div', 'world-archetype-grid');
    this.briefing!.event_archetypes.forEach((item) => {
      const card = el('article', `world-archetype-card${item.active ? ' is-active' : ''}`);
      card.append(
        el('span', '', item.active ? '今日出现' : '复盘模板'),
        el('h3', '', item.title),
        el('p', '', item.trigger),
        el('strong', '', item.path),
        el('small', '', `反证：${item.failure}`),
      );
      if (item.related_event_id) {
        const button = el('button', 'world-text-button', '打开今天的对应事件 →');
        button.type = 'button';
        button.addEventListener('click', () => this.navigate('events', { event: item.related_event_id ?? undefined }));
        card.appendChild(button);
      }
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderEventResearch(): HTMLElement {
    const briefing = this.briefing!;
    const requestedId = new URL(window.location.href).searchParams.get('event');
    const selected = briefing.events.find((event) => event.id === requestedId) ?? briefing.events[0];
    const container = el('div', 'world-research-page');
    const selector = el('div', 'world-entity-selector');
    briefing.events.forEach((event) => {
      const button = el(
        'button',
        event.id === selected?.id ? 'is-active' : '',
        `${String(event.rank).padStart(2, '0')} ${event.display_title}`,
      );
      button.type = 'button';
      button.addEventListener('click', () => this.navigate('events', { event: event.id }));
      selector.appendChild(button);
    });
    container.appendChild(selector);
    if (!selected) {
      container.appendChild(el('p', 'world-empty', '当前没有可核对的高影响事件。'));
      return container;
    }
    const orientation = el('section', 'world-research-orientation');
    orientation.append(
      el('span', 'world-mini-label', 'RESEARCH QUESTION'),
      el('h2', '', selected.core_question),
      el('p', '', selected.why_it_matters),
    );
    const coordinates = el('div', 'world-research-coordinates');
    [
      ['事件类型', selected.event_type],
      ['先变的预期', selected.expectation_shift],
      ['分析置信度', `${Math.round(selected.confidence * 100)}% · 假设`],
    ].forEach(([label, value]) => {
      const item = el('div');
      item.append(el('span', '', label), el('strong', '', value));
      coordinates.appendChild(item);
    });
    orientation.appendChild(coordinates);
    container.append(orientation, this.eventCard(selected, true, false));
    if (selected.id === briefing.events[0]?.id) {
      container.append(this.renderMacroChain(), this.renderDeepBrief(), this.renderValidation());
    } else {
      const note = el('section', 'world-section world-research-note');
      note.append(
        el('div', 'world-section-index', 'RESEARCH BOUNDARY'),
        el('h2', '', '这条事件怎样继续验证'),
        el('p', '', '当前八阶段总链条围绕排名第一的主事件生成；本事件先使用自己的因果链、确认项和反证，避免把不同冲击强行拼成一个故事。'),
      );
      container.appendChild(note);
    }
    const switcher = el('section', 'world-related-events');
    switcher.append(
      el('div', 'world-section-index', 'RELATED EVENTS'),
      el('h2', '', '切换其他重要事件'),
    );
    const cards = el('div', 'world-related-event-grid');
    briefing.events
      .filter((event) => event.id !== selected.id)
      .forEach((event) => {
        const button = el('button', '', event.display_title);
        button.type = 'button';
        button.appendChild(el('span', '', event.expectation_shift));
        button.addEventListener('click', () => this.navigate('events', { event: event.id }));
        cards.appendChild(button);
      });
    switcher.appendChild(cards);
    container.appendChild(switcher);
    return container;
  }

  private renderMarketResearch(): HTMLElement {
    const briefing = this.briefing!;
    const requestedKey = new URL(window.location.href).searchParams.get('market');
    const selected = briefing.markets.find((market) => market.key === requestedKey)
      ?? briefing.markets.find((market) => market.key === 'gold')
      ?? briefing.markets[0];
    const container = el('div', 'world-research-page');
    const selector = el('div', 'world-market-selector');
    briefing.markets.forEach((market) => {
      const button = el(
        'button',
        market.key === selected?.key ? `is-active world-move-${market.direction}` : '',
      );
      button.type = 'button';
      button.append(
        el('span', '', market.name_zh),
        el(
          'strong',
          '',
          formatMove(market.change_percent),
        ),
      );
      button.addEventListener('click', () => this.navigate('markets', { market: market.key }));
      selector.appendChild(button);
    });
    container.appendChild(selector);
    if (!selected) return container;

    const focus = el('section', `world-market-focus world-move-${selected.direction}`);
    const identity = el('div', 'world-market-focus-identity');
    identity.append(
      el('span', 'world-mini-label', `${selected.symbol} · ${selected.region}`),
      el('h2', '', selected.name_zh),
      el('p', '', selected.role),
    );
    const quote = el('div', 'world-market-focus-quote');
    quote.append(
      el('strong', '', formatPrice(selected)),
      el(
        'span',
        '',
        formatMove(selected.change_percent, '数据待更新'),
      ),
      renderSparkline(selected.sparkline, selected.direction),
    );
    focus.append(identity, quote);
    const analysis = el('div', 'world-market-analysis-grid');
    const blocks = [
      ['这个价格在回答什么', selected.question],
      ['今天可以怎样理解', selected.explanation],
      ['已经观察到什么', selected.evidence.join('；') || '当前没有第二项独立证据。'],
      [
        '仍然不知道什么',
        selected.order_flow_known
          ? '当前数据包含可核对的订单流证据。'
          : '免费公开数据无法识别具体基金订单或算法触发，只能验证价格与宏观变量。',
      ],
    ];
    blocks.forEach(([label, value]) => {
      const block = el('article');
      block.append(el('span', 'world-mini-label', label), el('p', '', value));
      analysis.appendChild(block);
    });
    focus.appendChild(analysis);
    if (selected.source_url) {
      focus.appendChild(externalLink(
        `${selected.source ?? '行情来源'} · 查看原始行情 ↗`,
        selected.source_url,
        'world-market-source-link',
      ));
    }
    container.append(
      focus,
      this.renderMarketHorizons(),
      this.renderCorrelations(),
      this.renderRegimeBoard(),
      this.renderMarketStrip(),
    );
    return container;
  }

  private renderMarketHorizons(): HTMLElement {
    const rows = this.briefing!.market_system.horizons;
    const section = el('section', 'world-section world-horizon-table');
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', 'MULTI-HORIZON TAPE'),
      el('h2', '', '不要让一天的涨跌覆盖更长的趋势'),
      el('p', '', '并排比较 1、5、20 个交易日，识别单日噪声、趋势延续与方向反转。'),
    );
    section.appendChild(heading);
    const table = el('div', 'world-horizon-grid');
    const head = el('div', 'world-horizon-row is-head');
    head.append(el('span', '', '资产'), el('span', '', '1日'), el('span', '', '5日'), el('span', '', '20日'));
    table.appendChild(head);
    const renderMove = (value: number | null): HTMLElement => el(
      'span',
      `world-move-${value === null ? 'unavailable' : value > 0 ? 'up' : value < 0 ? 'down' : 'flat'}`,
      formatMove(value, '—'),
    );
    rows.forEach((row) => {
      const line = el('div', 'world-horizon-row');
      line.append(
        el('strong', '', row.name),
        renderMove(row.one_day),
        renderMove(row.five_day),
        renderMove(row.twenty_day),
      );
      table.appendChild(line);
    });
    section.appendChild(table);
    return section;
  }

  private renderCorrelations(): HTMLElement {
    const system = this.briefing!.market_system;
    const section = el('section', 'world-section world-correlations');
    section.id = 'correlations';
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', 'ROLLING RELATIONSHIPS'),
      el('h2', '', '最近二十个共同交易日，资产怎样联动'),
      el('p', '', system.method),
    );
    section.appendChild(heading);
    const grid = el('div', 'world-correlation-grid');
    system.correlations.forEach((row) => {
      const value = row.correlation;
      const card = el('article', `world-correlation-card is-${value === null ? 'unknown' : value > 0.35 ? 'positive' : value < -0.35 ? 'negative' : 'weak'}`);
      card.append(
        el('span', '', row.label),
        el('strong', '', value === null ? '样本不足' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}`),
        el('p', '', row.interpretation),
        el('small', '', `${row.observations} 个共同观测`),
      );
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderMacroChain(): HTMLElement {
    const chain = this.briefing!.macro_chain;
    const section = el('section', 'world-section world-macro-chain');
    section.id = 'chain';
    const heading = el('div', 'world-section-heading world-chain-heading');
    const title = el('div');
    title.append(
      el('div', 'world-section-index', '01 / COMPLETE MACRO CHAIN'),
      el('h2', '', '一件事如何传遍整个世界'),
      el('p', '', '短期价格只是第三步。继续往后看，才能理解它会不会进入经济与下一轮政策。'),
    );
    const regime = el('div', 'world-chain-regime');
    regime.append(el('span', '', '当前假设'), el('strong', '', chain.scenario));
    heading.append(title, regime);
    section.appendChild(heading);

    const track = el('ol', 'world-chain-track');
    for (const stage of chain.stages) {
      const item = el(
        'li',
        `world-chain-stage is-${stage.state}${stage.key === chain.current_stage ? ' is-current' : ''}`,
      );
      const top = el('div', 'world-chain-stage-top');
      top.append(
        el('span', 'world-chain-number', stage.number),
        el('span', 'world-chain-horizon', stage.horizon),
      );
      item.append(top, el('h3', '', stage.title), el('p', '', stage.summary));
      const watch = el('ul', 'world-chain-watch');
      stage.watch.slice(0, 2).forEach((entry) => watch.appendChild(el('li', '', entry)));
      item.appendChild(watch);
      track.appendChild(item);
    }
    section.appendChild(track);

    const loop = el('div', 'world-chain-loop');
    loop.append(
      el('strong', '', '反馈回路'),
      el('p', '', chain.feedback_loop),
      el('span', '', chain.method),
    );
    section.appendChild(loop);

    const references = el('details', 'world-chain-references');
    references.appendChild(el('summary', '', '这套链条借鉴了哪些成熟框架？'));
    const sourceList = el('div', 'world-chain-source-list');
    sourceList.append(
      externalLink(
        '传导渠道 · IMF',
        'https://www.elibrary.imf.org/view/journals/001/2023/146/article-A001-en.xml',
      ),
      externalLink(
        '经济周期 · Bridgewater',
        'https://www.bridgewater.com/how-the-economic-machine-works',
      ),
      externalLink(
        '信用与领先指标 · The Macro Compass',
        'https://themacrocompass.substack.com/p/inflation-what-next',
      ),
    );
    references.append(
      sourceList,
      el('p', '', '机构框架用于解释机制；市场作者用于提出假设。二者都必须回到数据和价格验证。'),
    );
    section.appendChild(references);
    return section;
  }

  private renderDeepBrief(): HTMLElement {
    const brief = this.briefing!.deep_brief;
    const clawfeed = this.briefing!.integrations.clawfeed;
    const section = el('section', 'world-section world-deep-brief');
    section.id = 'deep';
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(
      el('div', 'world-section-index', '02 / EDITORIAL DEEP BRIEF'),
      el('h2', '', '今天这件事，应该怎样真正理解'),
      el('p', '', '直接给出事实、机制、价格证据、不同解释和下一步观察，不要求你完成任何作业。'),
    );
    const meta = el('div', 'world-deep-meta');
    meta.append(
      el(
        'strong',
        '',
        clawfeed.connected ? `ClawFeed 已连接 · ${clawfeed.editions} 期` : 'ClawFeed 编辑模式',
      ),
      el('span', '', brief.read_time),
    );
    heading.append(title, meta);
    section.appendChild(heading);

    const question = el('article', 'world-deep-question');
    question.append(
      el('span', 'world-mini-label', '先回答一个问题'),
      el('h3', '', brief.question),
      el('p', '', brief.bottom_line),
    );
    section.appendChild(question);

    const flow = el('div', 'world-deep-flow');
    brief.sections.forEach((item, index) => {
      const card = el('article', `world-deep-card is-${item.key}`);
      const cardTop = el('div', 'world-deep-card-top');
      cardTop.append(
        el('span', '', String(index + 1).padStart(2, '0')),
        el('span', '', item.label),
      );
      card.append(cardTop, el('h3', '', item.title), el('p', 'world-deep-body', item.body));
      if (item.detail) card.appendChild(el('p', 'world-deep-detail', item.detail));
      if (item.evidence?.length) {
        const evidence = el('div', 'world-deep-evidence');
        for (const row of item.evidence) {
          const line = el('div', `is-${row.verdict}`);
          line.append(
            el('strong', '', row.market),
            el('span', '', row.role),
            el('span', '', row.observed),
            el(
              'span',
              '',
              row.verdict === 'supports' ? '支持' : row.verdict === 'weakens' ? '削弱' : '待确认',
            ),
          );
          evidence.appendChild(line);
        }
        card.appendChild(evidence);
      }
      if (item.perspectives?.length) {
        const debate = el('div', 'world-deep-debate');
        for (const view of item.perspectives) {
          const viewCard = el('article');
          viewCard.append(
            el('span', '', `${view.class} · ${view.source}`),
            el('strong', '', view.claim),
            el('p', '', `${view.lens}：${view.caveat}`),
          );
          if (view.url) viewCard.appendChild(externalLink('原文 ↗', view.url));
          debate.appendChild(viewCard);
        }
        card.appendChild(debate);
      }
      if (item.watch?.length) {
        const watch = el('ul', 'world-deep-watch');
        item.watch.forEach((entry) => watch.appendChild(el('li', '', entry)));
        card.appendChild(watch);
      }
      flow.appendChild(card);
    });
    section.appendChild(flow);

    if (brief.external_editions.length) {
      const editions = el('details', 'world-clawfeed-editions');
      editions.appendChild(el('summary', '', '查看接入的 ClawFeed 每日版'));
      for (const edition of brief.external_editions) {
        const card = el('article');
        card.append(
          el('span', '', `${edition.type} · ${formatDate(edition.created_at)}`),
          el('p', '', edition.content),
          externalLink('在 ClawFeed 中打开 ↗', edition.url),
        );
        editions.appendChild(card);
      }
      section.appendChild(editions);
    }
    section.appendChild(el('p', 'world-edition-rule', brief.edition_rule));
    return section;
  }

  private renderIntegrationConsole(): HTMLElement {
    const integrations = this.briefing!.integrations;
    const agentReach = integrations.agent_reach_x;
    const section = el('section', 'world-section world-integration-console');
    section.id = 'calls';
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(
      el('div', 'world-section-index', '01 / RESEARCH CALLS'),
      el('h2', '', '今天的数据调用发生了什么'),
      el('p', '', '连接状态、缓存和单个来源的成功率都公开展示；Cookie 内容永远不会进入这里。'),
    );
    const health = el(
      'span',
      `world-integration-health ${agentReach.connected ? 'is-online' : ''}`,
      agentReach.connected
        ? `${agentReach.calls_succeeded}/${agentReach.calls_attempted} 路成功`
        : '等待连接',
    );
    heading.append(title, health);
    section.appendChild(heading);

    const summary = el('div', 'world-integration-summary');
    const summaryRows: Array<[string, string]> = [
      ['Agent Reach / X', agentReach.connected ? '只读连接正常' : agentReach.state],
      ['本轮公开推文', `${agentReach.items} 条`],
      ['缓存策略', agentReach.cache.hit ? `命中缓存 · ${agentReach.cache.age_seconds ?? 0} 秒前` : `新调用 · ${Math.round(agentReach.cache.ttl_seconds / 60)} 分钟复用`],
      ['官方 X API', integrations.x.configured ? `${integrations.x.items} 条` : '未配置，不影响 Cookie 接入'],
      ['ClawFeed', integrations.clawfeed.connected ? `${integrations.clawfeed.editions} 个版本` : '使用内置编辑流'],
      ['WebMCP', `${integrations.webmcp.tools.length} 个页面工具`],
    ];
    summaryRows.forEach(([label, value]) => {
      const item = el('div');
      item.append(el('span', '', label), el('strong', '', value));
      summary.appendChild(item);
    });
    section.appendChild(summary);

    const ledger = el('div', 'world-call-ledger');
    const ledgerHead = el('div', 'world-call-row world-call-head');
    ledgerHead.append(
      el('span', '', '来源'),
      el('span', '', '研究角色'),
      el('span', '', '结果'),
      el('span', '', '条目'),
      el('span', '', '耗时'),
    );
    ledger.appendChild(ledgerHead);
    if (!agentReach.calls.length) {
      ledger.appendChild(el('p', 'world-empty', '当前没有执行 X 调用。请确认 Agent Reach 与本地 Cookie 配置。'));
    }
    agentReach.calls.forEach((call) => {
      const row = el('div', 'world-call-row');
      const source = el('span', 'world-call-source');
      source.append(el('strong', '', call.label), el('small', '', call.handle));
      const statusLabel = call.status === 'ok'
        ? '成功'
        : call.status === 'timeout' ? '超时' : '失败';
      row.append(
        source,
        el('span', '', call.research_role),
        el('span', `world-call-status is-${call.status}`, statusLabel),
        el('span', '', String(call.items)),
        el('span', '', `${(call.duration_ms / 1000).toFixed(1)}s`),
      );
      ledger.appendChild(row);
    });
    section.appendChild(ledger);
    section.appendChild(el(
      'p',
      'world-method-note',
      '安全边界：凭据只从本机 Agent Reach 配置读取，并只注入 twitter-cli 子进程；网页、接口响应、日志和 Git 均不接触凭据值。',
    ));
    return section;
  }

  private renderPerspectives(limit?: number, compact = false): HTMLElement {
    const briefing = this.briefing!;
    const section = el('section', `world-section world-perspectives${compact ? ' is-compact' : ''}`);
    section.id = 'perspectives';
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', '03 / VIEWPOINT LAB'),
      el('h2', '', '观点不是答案，而是可以被检验的假设'),
      el('p', '', '机构研究负责机制，市场作者负责提出线索；每一条都要翻译成数据与价格。'),
    );
    section.appendChild(heading);

    const xState = briefing.integrations.x;
    const agentReach = briefing.integrations.agent_reach_x;
    const notice = el('div', `world-x-notice ${agentReach.connected || xState.configured ? 'is-connected' : ''}`);
    notice.append(
      el(
        'strong',
        '',
        agentReach.connected
          ? `Agent Reach 已连接 X · ${agentReach.calls_succeeded} 路来源 · ${agentReach.items} 条`
          : xState.configured ? `X 官方接口已连接 · 今日 ${xState.items} 条` : 'X 数据源尚未连接',
      ),
      el(
        'p',
        '',
        agentReach.connected || xState.configured
          ? 'X 内容只作为实时线索，仍需原始数据和跨资产价格确认。'
          : '公开机构与 Newsletter 仍会每日更新；X 接入失败不会阻断事实简报和市场数据。',
      ),
    );
    section.appendChild(notice);

    const grid = el('div', 'world-perspective-grid');
    if (!briefing.perspectives.length) {
      grid.appendChild(
        el('p', 'world-empty', '公开观点源本次没有返回内容；事实简报和宏观课程仍可正常使用。'),
      );
    }
    const visiblePerspectives = limit === undefined
      ? briefing.perspectives
      : briefing.perspectives.slice(0, limit);
    for (const view of visiblePerspectives) {
      const card = el('article', `world-perspective-card is-${view.source_class}`);
      const meta = el('div', 'world-perspective-meta');
      meta.append(
        el('span', 'world-perspective-class', view.source_class_label),
        el(
          'span',
          `world-relevance-badge is-${view.relevance_score >= 66 ? 'direct' : view.relevance_score >= 30 ? 'mechanism' : 'background'}`,
          `${view.relevance_label} · ${view.relevance_score}`,
        ),
        el('span', '', `${view.source} · ${formatDate(view.published_at, false)}`),
      );
      card.append(
        meta,
        el('h3', '', view.title),
        el('p', 'world-perspective-claim', view.claim),
      );
      if (view.channel === 'agent_reach_x') {
        const provenance = el('div', 'world-perspective-provenance');
        provenance.append(
          el('span', '', view.account_class ?? 'X source'),
          el('span', '', view.research_role ?? '实时研究线索'),
          el(
            'span',
            '',
            view.engagement ? `${view.engagement.toLocaleString()} 次公开互动` : '互动量待确认',
          ),
        );
        card.appendChild(provenance);
      }
      const mechanism = el('div', 'world-perspective-mechanism');
      mechanism.append(
        el('span', 'world-mini-label', `研究镜头 · ${view.lens}`),
        el('p', '', view.translation),
      );
      const tests = el('div', 'world-perspective-tests');
      view.test_with.forEach((item) => tests.appendChild(el('span', '', item)));
      card.append(
        mechanism,
        tests,
        el('p', 'world-perspective-relevance', view.relevance_reason),
        el('p', 'world-perspective-caveat', `限制：${view.caveat}`),
        externalLink('阅读原文 ↗', view.url, 'world-perspective-link'),
      );
      grid.appendChild(card);
    }
    section.appendChild(grid);
    return section;
  }

  private renderSourceWorkbench(): HTMLElement {
    const briefing = this.briefing!;
    const section = el('section', 'world-section world-source-workbench');
    section.id = 'sources';
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', '03 / SOURCE MAP'),
      el('h2', '', '来源不是一锅粥：每一类解决不同问题'),
      el('p', '', '事实源确认发生了什么，观点源提出机制，价格源负责确认，宏观数据负责判断持续性。'),
    );
    section.appendChild(heading);
    const groups: Array<{
      title: string;
      question: string;
      sources: string[];
      warning: string;
    }> = [
      {
        title: '事实与事件',
        question: '发生了什么？发布时间是什么？',
        sources: briefing.sources.news,
        warning: '新闻摘要不能替代原文，也不能自动证明价格因果。',
      },
      {
        title: '观点与假设',
        question: '可能通过什么机制传导？',
        sources: briefing.sources.perspectives,
        warning: '机构与作者都可能有模型、仓位或叙事偏差。',
      },
      {
        title: '跨资产价格',
        question: '市场是否在确认这条链？',
        sources: briefing.sources.markets,
        warning: '日线免费行情不是交易所级实时数据，也看不到私人订单流。',
      },
      {
        title: '长期宏观底座',
        question: '冲击会持续还是均值回归？',
        sources: briefing.sources.macro,
        warning: '宏观数据有发布时滞和修订，需要保留数据版本。',
      },
    ];
    const grid = el('div', 'world-source-map-grid');
    groups.forEach((group) => {
      const card = el('article');
      card.append(
        el('h3', '', group.title),
        el('strong', '', group.question),
      );
      const chips = el('div', 'world-source-chips');
      (group.sources.length ? group.sources : ['本轮暂无可用来源']).forEach((source) => {
        chips.appendChild(el('span', '', source));
      });
      card.append(chips, el('p', '', group.warning));
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderMarketStrip(limit?: number): HTMLElement {
    const section = el('section', 'world-market-section');
    section.id = 'markets';
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', '06 / MARKET ROLES'),
      el('h2', '', '每个市场在回答什么问题'),
      el('p', '', '不要孤立读涨跌；先看它在宏观链条中的角色。'),
    );
    section.appendChild(heading);
    const grid = el('div', 'world-market-grid');
    for (const market of this.briefing!.markets.slice(0, limit)) {
      grid.appendChild(this.marketCard(market));
    }
    section.appendChild(grid);
    return section;
  }

  private marketCard(market: WorldMarket): HTMLElement {
    const card = el('article', `world-market-card world-move-${market.direction}`);
    const top = el('div', 'world-market-top');
    const identity = el('div');
    identity.append(
      el('span', 'world-market-name', market.name_zh),
      el('span', 'world-market-role', market.role),
    );
    top.append(identity, el('span', 'world-market-symbol', market.symbol));
    const value = el('div', 'world-market-value');
    const price = el('strong', '', formatPrice(market));
    const change = el(
      'span',
      '',
      formatMove(market.change_percent, '数据待更新'),
    );
    value.append(price, change);
    card.append(top, value, renderSparkline(market.sparkline, market.direction));
    const explanation = el('p', 'world-market-explanation', market.explanation);
    card.appendChild(explanation);
    const open = el('button', 'world-card-open', '进入市场实验室 →');
    open.type = 'button';
    open.addEventListener('click', () => this.navigate('markets', { market: market.key }));
    card.appendChild(open);
    const footer = el('div', 'world-market-footer');
    footer.append(
      market.source_url
        ? externalLink(market.source ?? '行情来源', market.source_url)
        : el('span', '', '来源暂不可用'),
    );
    card.appendChild(footer);
    return card;
  }

  private renderEvents(limit?: number): HTMLElement {
    const section = el('section', 'world-section');
    section.id = 'events';
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(
      el('div', 'world-section-index', '04 / TOP WORLD EVENTS'),
      el('h2', '', '今天全球最重要的事情'),
      el('p', '', '不是把新闻变长，而是找出它改变了什么预期。'),
    );
    heading.appendChild(title);
    section.appendChild(heading);
    const list = el('div', 'world-event-list');
    if (!this.briefing!.events.length) {
      list.appendChild(el('p', 'world-empty', '免费新闻源暂时没有返回可核对的高影响事件。'));
    }
    this.briefing!.events
      .slice(0, limit)
      .forEach((event) => list.appendChild(this.eventCard(event)));
    section.appendChild(list);
    return section;
  }

  private eventCard(event: WorldEvent, open = false, showResearchLink = true): HTMLElement {
    const details = el('details', 'world-event-card');
    details.open = open;
    const summary = el('summary', 'world-event-summary');
    const rank = el('span', 'world-event-rank', String(event.rank).padStart(2, '0'));
    const content = el('div', 'world-event-title-block');
    const meta = el('div', 'world-event-meta');
    meta.append(
      el('span', 'world-category', event.source),
      el('span', '', formatDate(event.published_at)),
    );
    content.append(
      meta,
      el('h3', '', event.display_title),
      el('p', 'world-event-deck', event.why_it_matters),
    );
    summary.append(rank, content, el('span', 'world-expand', '查看分析'));
    details.appendChild(summary);

    const body = el('div', 'world-event-body');
    const shift = el('div', 'world-expectation-shift');
    shift.append(
      el('span', 'world-mini-label', '市场可能在重新定价'),
      el('strong', '', event.expectation_shift),
    );
    const chain = el('ol', 'world-causal-chain');
    event.causal_chain.forEach((step, index) => {
      const item = el('li');
      item.append(
        el('span', '', event.chain_labels[index] ?? String(index + 1)),
        el('p', '', step),
      );
      chain.appendChild(item);
    });
    const tests = el('div', 'world-test-grid');
    const support = el('article', 'world-test-support');
    support.appendChild(el('span', 'world-mini-label', '什么会支持'));
    const supportList = el('ul');
    event.confirmations.slice(0, 2).forEach((item) => supportList.appendChild(el('li', '', item)));
    support.appendChild(supportList);
    const weaken = el('article', 'world-test-weaken');
    weaken.appendChild(el('span', 'world-mini-label', '什么会推翻'));
    const weakenList = el('ul');
    event.falsifiers.slice(0, 2).forEach((item) => weakenList.appendChild(el('li', '', item)));
    weaken.appendChild(weakenList);
    const alternative = el('article', 'world-test-alternative');
    alternative.appendChild(el('span', 'world-mini-label', '替代解释'));
    const alternativeList = el('ul');
    event.alternatives.slice(0, 2).forEach((item) => alternativeList.appendChild(el('li', '', item)));
    alternative.appendChild(alternativeList);
    tests.append(support, weaken, alternative);
    const source = el('div', 'world-event-source');
    source.append(
      el('span', 'world-mini-label', '已知事实'),
      externalLink(event.title, event.url, 'world-original-headline'),
    );
    body.append(
      source,
      shift,
      el('div', 'world-mini-label', '理解链'),
      chain,
      tests,
    );
    if (showResearchLink) {
      const research = el('button', 'world-card-open', '进入事件研究页 →');
      research.type = 'button';
      research.addEventListener('click', () => this.navigate('events', { event: event.id }));
      body.appendChild(research);
    }
    details.appendChild(body);
    return details;
  }

  private renderValidation(): HTMLElement {
    const validation = this.briefing!.lead_validation;
    const section = el('section', 'world-section world-validation');
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', '05 / HYPOTHESIS CHECK'),
      el('h2', '', '市场在确认这条主线吗？'),
      el('p', '', '把事前方向与实际价格并排，避免看完涨跌再编故事。'),
    );
    section.appendChild(heading);
    const verdict = el('div', `world-validation-verdict is-${validation.status}`);
    verdict.append(
      el('span', '', validation.label),
      el('strong', '', validation.scenario ?? '方向待确认'),
      el('p', '', validation.summary),
    );
    section.appendChild(verdict);
    if (validation.rows.length) {
      const table = el('div', 'world-validation-table');
      const head = el('div', 'world-validation-row world-validation-head');
      head.append(
        el('span', '', '定价变量'),
        el('span', '', '假设方向'),
        el('span', '', '实际方向'),
        el('span', '', '判断'),
      );
      table.appendChild(head);
      for (const row of validation.rows) {
        const line = el('div', 'world-validation-row');
        const identity = el('span', 'world-validation-market');
        identity.append(el('strong', '', row.market_name), el('small', '', row.role));
        const statusText =
          row.status === 'supports' ? '支持' : row.status === 'weakens' ? '削弱' : '待确认';
        line.append(
          identity,
          el('span', '', row.expected_label),
          el('span', '', row.observed_label),
          el('span', `world-validation-status is-${row.status}`, statusText),
        );
        table.appendChild(line);
      }
      section.appendChild(table);
    }
    if (validation.timing_note) {
      section.appendChild(el('p', 'world-method-note', validation.timing_note));
    }
    return section;
  }

  private renderLesson(): HTMLElement {
    const lesson = this.briefing!.lesson;
    const section = el('section', 'world-section world-lesson');
    section.id = 'learn';
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', '07 / RETRIEVAL PRACTICE'),
      el('h2', '', `今天真正学会：${lesson.concept}`),
      el('p', '', '这是理解检查，不是作业；想确认自己是否读懂时再展开。'),
    );
    const body = el('div', 'world-learning-loop');
    const question = el('article', 'world-learning-question');
    question.append(
      el('span', 'world-mini-label', '01 · 先回答'),
      el('h3', '', lesson.question),
    );
    const reveal = el('details', 'world-answer-reveal');
    const revealSummary = el('summary', '', '查看思路');
    const worked = el('ol', 'world-learning-chain');
    lesson.worked_example.forEach((step) => worked.appendChild(el('li', '', step)));
    reveal.append(revealSummary, worked, el('p', '', lesson.retrieval_answer));
    const transfer = el('article', 'world-learning-transfer');
    transfer.append(
      el('span', 'world-mini-label', '02 · 换个情境'),
      el('p', '', lesson.transfer_question),
    );
    body.append(question, reveal, transfer);
    section.append(heading, body);
    return section;
  }

  private renderCurriculum(): HTMLElement {
    const section = el('details', 'world-section world-curriculum');
    section.id = 'course';
    const summary = el('summary', 'world-curriculum-summary');
    const heading = el('div');
    heading.append(
      el('div', 'world-section-index', '08 / OPTIONAL LEARNING REFERENCES'),
      el('h2', '', '想系统学习时，再打开这些免费课程'),
      el('p', '', '平时不需要按课程打卡；这里只在你想补某个概念时提供可靠入口。'),
    );
    summary.append(heading, el('span', 'world-count', '可选参考'));
    section.appendChild(summary);
    const grid = el('div', 'world-course-grid');
    for (const module of this.briefing!.curriculum) {
      const card = el('article', 'world-course-card');
      const meta = el('div', 'world-course-meta');
      meta.append(
        el('span', '', module.number),
        el('span', '', module.level),
        el('span', '', module.duration),
      );
      card.append(meta, el('h3', '', module.title), el('p', 'world-course-question', module.question));
      const outcomes = el('ul', 'world-course-outcomes');
      module.outcomes.forEach((item) => outcomes.appendChild(el('li', '', item)));
      card.appendChild(outcomes);
      const resources = el('div', 'world-course-resources');
      for (const resource of module.resources) {
        const link = externalLink(resource.title, resource.url);
        link.appendChild(el('small', '', `${resource.provider} · ${resource.access}`));
        resources.appendChild(link);
      }
      card.appendChild(resources);
      grid.appendChild(card);
    }
    section.appendChild(grid);
    return section;
  }

  private renderMacroFoundation(): HTMLElement {
    const context = this.briefing!.macro_context;
    const section = el('details', 'world-section world-foundation');
    const summary = el('summary', 'world-foundation-summary');
    const title = el('div');
    title.append(el('div', 'world-kicker', 'MACRO FOUNDATION'), el('h2', '', '查看长期宏观底座'));
    summary.append(title, el('span', 'world-count', context.mode));
    const states = el('div', 'world-state-strip');
    for (const state of context.states) {
      const card = el('div', 'world-state-chip');
      card.append(
        el('span', '', state.key.replace(/_/g, ' ')),
        el('strong', '', state.score === null ? '数据不足' : `${state.score >= 0 ? '+' : ''}${state.score.toFixed(2)}`),
      );
      states.appendChild(card);
    }
    section.append(summary, states);
    return section;
  }

  private renderMethodLibrary(): HTMLElement {
    const section = el('section', 'world-section world-method-library');
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', 'METHOD & PRODUCT REFERENCES'),
      el('h2', '', '这套研究工作区借鉴了什么'),
      el('p', '', '只吸收可解释的产品原则和信息结构；不会把大型项目、交易建议或不明来源代码直接混进终端。'),
    );
    section.appendChild(heading);
    const references = [
      {
        title: 'BettaFish',
        adopted: '多来源观点、破除信息茧房、把相互冲突的解释并列呈现。',
        boundary: '不引入其完整多智能体和爬虫系统；当前仍以可核对、免费、低风险来源为主。',
        url: 'https://github.com/666ghj/BettaFish',
      },
      {
        title: 'daily_stock_analysis',
        adopted: '结构化摘要、多数据源失败降级、报告完整性与来源时效意识。',
        boundary: '不采用买卖点、止盈止损等交易导向功能。',
        url: 'https://github.com/ZhuLinsen/daily_stock_analysis',
      },
      {
        title: 'Hermes HUD',
        adopted: '把健康、会话、成本和调用状态作为一等页面，而不是藏在后台日志。',
        boundary: '当前只展示研究调用，不读取其他 Agent 的私人记忆。',
        url: 'https://github.com/joeynyc/hermes-hudui',
      },
      {
        title: 'Lumina Note',
        adopted: '本地优先、知识工作区、多视图导航以及“用户决定什么发送给 AI”。',
        boundary: '暂不复制其编辑器、知识图谱和插件运行时。',
        url: 'https://github.com/blueberrycongee/Lumina-Note',
      },
    ];
    const grid = el('div', 'world-method-reference-grid');
    references.forEach((reference) => {
      const card = el('article');
      card.append(
        externalLink(`${reference.title} ↗`, reference.url),
        el('strong', '', '采用'),
        el('p', '', reference.adopted),
        el('strong', '', '边界'),
        el('p', '', reference.boundary),
      );
      grid.appendChild(card);
    });
    section.appendChild(grid);
    return section;
  }

  private renderTutor(): HTMLElement {
    const briefing = this.briefing!;
    const aside = el('aside', 'world-tutor');
    const header = el('div', 'world-tutor-header');
    const identity = el('div');
    identity.append(el('div', 'world-kicker', 'AI WORLD TUTOR'), el('h2', '', '向世界提问'));
    const provider = el(
      'span',
      `world-ai-status ${briefing.ai.available ? 'is-online' : ''}`,
      briefing.ai.available ? `${briefing.ai.provider} · ${briefing.ai.model}` : '证据规则模式',
    );
    header.append(identity, provider);
    aside.appendChild(header);
    aside.appendChild(
      el('p', 'world-tutor-intro', '问一个具体问题，我会按“预期差 → 变量 → 证据 → 反证”回答。'),
    );

    const modes = el('div', 'world-tutor-modes');
    const modeLabels: Array<[TutorMode, string]> = [
      ['beginner', '讲简单点'],
      ['deep', '深度推理'],
      ['socratic', '引导学习'],
    ];
    for (const [mode, label] of modeLabels) {
      const button = el('button', this.tutorMode === mode ? 'is-active' : '', label);
      button.type = 'button';
      button.addEventListener('click', () => {
        this.tutorMode = mode;
        this.render();
      });
      modes.appendChild(button);
    }
    aside.appendChild(modes);

    const messages = el('div', 'world-tutor-messages');
    if (!this.tutorEntries.length) {
      const suggestions: Record<WorldView, string[]> = {
        overview: [
          '今天最重要的事情为什么会影响市场？',
          '市场现在共同在定价什么？',
          '今天最容易被误读的信号是什么？',
        ],
        events: [
          '把主事件的完整传导链讲清楚。',
          '哪种替代解释最可能推翻当前主线？',
          '算法交易在消息发布后扮演什么角色？',
        ],
        calendar: [
          '下一项高影响数据可能怎样影响黄金和美债？',
          '怎样做一次央行会议前的情景预演？',
          '公布后为什么不能只看第一分钟价格？',
        ],
        markets: [
          '黄金今天为什么涨跌？',
          '哪些资产正在相互确认，哪些正在背离？',
          '1日、5日和20日表现应该怎样一起看？',
        ],
        themes: [
          '今天最强的宏观主题是怎样形成的？',
          '中国、美国与亚洲市场之间有什么传导？',
          '把能源主题从供应一直讲到央行政策。',
        ],
        signals: [
          '哪些外部观点与今日主线直接相关？',
          '怎样判断一个 X 观点值不值得继续验证？',
          '今天的证据链还缺哪一环？',
        ],
        library: [
          '我应该用哪一种事件模板理解今天？',
          '怎样区分相关性、领先关系和因果冲击？',
          '给我一条从入门到深入的学习路径。',
        ],
      };
      const welcome = el('div', 'world-tutor-welcome');
      welcome.append(el('strong', '', '从当前工作区继续追问'));
      suggestions[this.currentView].forEach((question) => {
        welcome.appendChild(this.suggestionButton(question));
      });
      messages.appendChild(welcome);
    }
    for (const entry of this.tutorEntries) messages.appendChild(this.renderTutorEntry(entry));
    if (this.tutorBusy) messages.appendChild(el('div', 'world-tutor-thinking', '正在核对证据并组织解释…'));
    aside.appendChild(messages);

    const form = el('form', 'world-tutor-form');
    const textarea = el('textarea');
    textarea.name = 'question';
    textarea.placeholder = '例如：为什么美联储讲话会让黄金突然波动？';
    textarea.maxLength = 3000;
    textarea.rows = 3;
    textarea.disabled = this.tutorBusy;
    const submit = el('button', 'world-primary-button', this.tutorBusy ? '分析中…' : '提问');
    submit.type = 'submit';
    submit.disabled = this.tutorBusy;
    form.append(textarea, submit);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const question = textarea.value.trim();
      if (question) void this.askTutor(question);
    });
    aside.appendChild(form);
    aside.appendChild(el('p', 'world-disclaimer', '关键结论可回到原始来源核对。'));
    queueMicrotask(() => {
      messages.scrollTop = messages.scrollHeight;
    });
    return aside;
  }

  private suggestionButton(question: string): HTMLButtonElement {
    const button = el('button', '', question);
    button.type = 'button';
    button.addEventListener('click', () => void this.askTutor(question));
    return button;
  }

  private renderTutorEntry(entry: TutorEntry): HTMLElement {
    const article = el('article', `world-message world-message-${entry.role}`);
    article.appendChild(el('span', 'world-message-role', entry.role === 'user' ? '你' : '世界导师'));
    article.appendChild(el('p', '', entry.content));
    if (entry.provider) article.appendChild(el('span', 'world-message-provider', entry.provider));
    if (entry.citations?.length) {
      const sources = el('div', 'world-message-sources');
      entry.citations.slice(0, 5).forEach((source, index) => {
        sources.appendChild(externalLink(`[S${index + 1}] ${source.source}`, source.url));
      });
      article.appendChild(sources);
    }
    return article;
  }

  private async askTutor(question: string): Promise<void> {
    if (this.tutorBusy) return;
    const history: TutorMessage[] = this.tutorEntries.map(({ role, content }) => ({ role, content }));
    this.tutorEntries.push({ role: 'user', content: question });
    this.tutorBusy = true;
    this.render();
    try {
      const response = await askWorldTutor(question, this.tutorMode, history);
      this.tutorEntries.push({
        role: 'assistant',
        content: response.answer,
        provider: `${response.provider} · ${response.model}`,
        citations: response.citations,
      });
    } catch (error) {
      this.tutorEntries.push({
        role: 'assistant',
        content: error instanceof Error ? `暂时无法回答：${error.message}` : '暂时无法回答。',
        provider: 'system',
      });
    } finally {
      this.tutorBusy = false;
      this.render();
    }
  }

  private renderFooter(): HTMLElement {
    const footer = el('footer', 'world-footer');
    footer.append(el('span', '', '日线价格 · 来源可核对 · 因果解释可被反证'));
    return footer;
  }

  public destroy(): void {
    this.controller?.abort();
    if (this.refreshTimer !== null) window.clearInterval(this.refreshTimer);
    window.removeEventListener('popstate', this.handlePopState);
  }
}
