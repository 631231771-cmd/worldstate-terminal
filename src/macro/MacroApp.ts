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
import './macro-terminal.css';

const SVG_NS = 'http://www.w3.org/2000/svg';

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

function confidenceLabel(value: number): string {
  if (value >= 0.75) return '较高';
  if (value >= 0.55) return '中等';
  if (value > 0) return '较低';
  return '未知';
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

export class MacroApp {
  private readonly root: HTMLElement;
  private controller: AbortController | null = null;
  private briefing: WorldBriefing | null = null;
  private tutorMode: TutorMode = 'beginner';
  private tutorEntries: TutorEntry[] = [];
  private tutorBusy = false;
  private refreshTimer: number | null = null;

  constructor(rootId: string) {
    const root = document.getElementById(rootId);
    if (!root) throw new Error(`Missing application root #${rootId}`);
    this.root = root;
  }

  public async init(): Promise<void> {
    this.applyDefaultLanguage();
    await initI18n();
    document.title = '世界状态终端 · 每日世界解释';
    this.renderLoading();
    await this.refresh(false);
    this.refreshTimer = window.setInterval(() => void this.refresh(false), 5 * 60_000);
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
    shell.append(
      this.renderHeader(),
      this.renderHero(),
      this.renderMarketStrip(),
    );

    const content = el('div', 'world-content-grid');
    const editorial = el('div', 'world-editorial-column');
    editorial.append(
      this.renderEvents(),
      this.renderTransmission(),
      this.renderLesson(),
      this.renderMacroFoundation(),
    );
    content.append(editorial, this.renderTutor());
    shell.appendChild(content);
    shell.appendChild(this.renderFooter());
    this.root.replaceChildren(shell);
  }

  private renderHeader(): HTMLElement {
    const briefing = this.briefing!;
    const header = el('header', 'world-topbar');
    const brand = el('div', 'world-brand');
    brand.append(
      el('span', 'world-brand-mark', 'WST'),
      el('div', 'world-brand-copy', '世界状态终端'),
    );
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
    header.append(brand, meta);
    return header;
  }

  private renderHero(): HTMLElement {
    const briefing = this.briefing!;
    const hero = el('section', 'world-hero');
    const copy = el('div', 'world-hero-copy');
    copy.append(
      el('div', 'world-kicker', `TODAY'S WORLD · ${formatDate(briefing.generated_at, false)}`),
      el('h1', '', briefing.headline),
      el('p', 'world-mission', briefing.mission),
    );
    const orientation = el('div', 'world-orientation');
    orientation.append(
      el('span', 'world-orientation-label', '阅读方法'),
      el('strong', '', '事实 → 预期 → 传导 → 市场确认'),
      el('p', '', '我们不把“有人买入”当成最终原因，也不会假装知道看不见的机构订单流。'),
    );
    hero.append(copy, orientation);
    return hero;
  }

  private renderMarketStrip(): HTMLElement {
    const section = el('section', 'world-market-section');
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-kicker', 'GLOBAL MARKET PULSE'),
      el('h2', '', '全球市场正在怎样反应'),
      el('p', '', '日线免费行情 · 点击来源可核对原始数据'),
    );
    section.appendChild(heading);
    const grid = el('div', 'world-market-grid');
    for (const market of this.briefing!.markets) grid.appendChild(this.marketCard(market));
    section.appendChild(grid);
    return section;
  }

  private marketCard(market: WorldMarket): HTMLElement {
    const card = el('article', `world-market-card world-move-${market.direction}`);
    const top = el('div', 'world-market-top');
    top.append(
      el('span', 'world-market-name', market.name_zh),
      el('span', 'world-market-symbol', market.symbol),
    );
    const value = el('div', 'world-market-value');
    const price = el('strong', '', formatPrice(market));
    const change = el(
      'span',
      '',
      market.change_percent === undefined ? '数据待更新' : `${market.change_percent >= 0 ? '+' : ''}${market.change_percent.toFixed(2)}%`,
    );
    value.append(price, change);
    card.append(top, value, renderSparkline(market.sparkline, market.direction));
    const explanation = el('p', 'world-market-explanation', market.explanation);
    card.appendChild(explanation);
    const footer = el('div', 'world-market-footer');
    footer.append(
      el('span', '', `解释信心 ${confidenceLabel(market.confidence)}`),
      market.source_url
        ? externalLink(market.source ?? '行情来源', market.source_url)
        : el('span', '', '来源暂不可用'),
    );
    card.appendChild(footer);
    return card;
  }

  private renderEvents(): HTMLElement {
    const section = el('section', 'world-section');
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(
      el('div', 'world-kicker', 'TOP WORLD EVENTS'),
      el('h2', '', '今天全球最重要的事情'),
    );
    heading.append(title, el('span', 'world-count', `${this.briefing!.events.length} 个主题`));
    section.appendChild(heading);
    const list = el('div', 'world-event-list');
    if (!this.briefing!.events.length) {
      list.appendChild(el('p', 'world-empty', '免费新闻源暂时没有返回可核对的高影响事件。'));
    }
    this.briefing!.events.forEach((event, index) => list.appendChild(this.eventCard(event, index)));
    section.appendChild(list);
    return section;
  }

  private eventCard(event: WorldEvent, index: number): HTMLElement {
    const details = el('details', 'world-event-card');
    details.open = index === 0;
    const summary = el('summary', 'world-event-summary');
    const rank = el('span', 'world-event-rank', String(event.rank).padStart(2, '0'));
    const content = el('div', 'world-event-title-block');
    const meta = el('div', 'world-event-meta');
    meta.append(
      el('span', 'world-category', event.category.replace('_', ' ')),
      el('span', '', formatDate(event.published_at)),
      el('span', '', `重要度 ${event.importance}`),
    );
    content.append(meta, el('h3', '', event.display_title));
    summary.append(rank, content, el('span', 'world-expand', '展开'));
    details.appendChild(summary);

    const body = el('div', 'world-event-body');
    const why = el('div', 'world-event-why');
    why.append(
      el('span', 'world-mini-label', '原始报道'),
      externalLink(event.title, event.url, 'world-original-headline'),
      el('span', 'world-mini-label', '为什么重要'),
      el('p', '', event.why_it_matters),
    );
    const chain = el('ol', 'world-causal-chain');
    for (const step of event.causal_chain) chain.appendChild(el('li', '', step));
    const evidence = el('div', 'world-event-evidence');
    evidence.append(
      el('span', '', `因果解释：假设 · 信心 ${confidenceLabel(event.confidence)}`),
      externalLink(`${event.source} · 查看原文`, event.url),
    );
    body.append(why, el('div', 'world-mini-label', '可能的传导链'), chain, evidence);
    details.appendChild(body);
    return details;
  }

  private renderTransmission(): HTMLElement {
    const event = this.briefing!.events[0];
    const section = el('section', 'world-section world-transmission');
    const heading = el('div', 'world-section-heading');
    heading.append(el('div', 'world-kicker', 'TRANSMISSION MAP'), el('h2', '', '一件事如何穿过市场'));
    section.appendChild(heading);
    if (!event) {
      section.appendChild(el('p', 'world-empty', '等待高影响事件后生成传导图。'));
      return section;
    }
    const map = el('div', 'world-transmission-map');
    event.causal_chain.forEach((step, index) => {
      const node = el('div', 'world-transmission-node');
      node.append(el('span', '', String(index + 1)), el('strong', '', step));
      map.appendChild(node);
      if (index < event.causal_chain.length - 1) map.appendChild(el('span', 'world-arrow', '→'));
    });
    section.appendChild(map);
    const note = el(
      'p',
      'world-method-note',
      '第一段波动可能由关键词算法、止损和期权对冲放大；行情能否持续，要看利率、美元和其他资产是否继续确认。',
    );
    section.appendChild(note);
    return section;
  }

  private renderLesson(): HTMLElement {
    const lesson = this.briefing!.lesson;
    const section = el('section', 'world-section world-lesson');
    const heading = el('div', 'world-section-heading');
    heading.append(el('div', 'world-kicker', 'DAILY LEARNING'), el('h2', '', `今日学习：${lesson.concept}`));
    const body = el('div', 'world-lesson-grid');
    const simple = el('article');
    simple.append(el('span', 'world-mini-label', '先这样理解'), el('h3', '', lesson.question), el('p', '', lesson.simple));
    const deep = el('article');
    deep.append(el('span', 'world-mini-label', '再深一层'), el('p', '', lesson.deep));
    const check = el('article', 'world-lesson-check');
    check.append(el('span', 'world-mini-label', '检验自己'), el('p', '', lesson.check_question));
    body.append(simple, deep, check);
    section.append(heading, body);
    return section;
  }

  private renderMacroFoundation(): HTMLElement {
    const context = this.briefing!.macro_context;
    const section = el('section', 'world-section world-foundation');
    const heading = el('div', 'world-section-heading world-heading-row');
    const title = el('div');
    title.append(el('div', 'world-kicker', 'MACRO FOUNDATION'), el('h2', '', '支撑解释的宏观底座'));
    heading.append(title, el('span', 'world-count', context.mode));
    const states = el('div', 'world-state-strip');
    for (const state of context.states) {
      const card = el('div', 'world-state-chip');
      card.append(
        el('span', '', state.key.replace(/_/g, ' ')),
        el('strong', '', state.score === null ? '数据不足' : `${state.score >= 0 ? '+' : ''}${state.score.toFixed(2)}`),
      );
      states.appendChild(card);
    }
    section.append(heading, states);
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
      el('p', 'world-tutor-intro', '回答使用本页同一组新闻与市场证据；没有AI Key时仍可进行基础因果教学。'),
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
      const welcome = el('div', 'world-tutor-welcome');
      welcome.append(
        el('strong', '', '你可以从这些问题开始'),
        this.suggestionButton('今天最重要的事情为什么会影响市场？'),
        this.suggestionButton('黄金今天为什么涨跌？'),
        this.suggestionButton('算法交易在新闻发布后扮演什么角色？'),
      );
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
    aside.appendChild(el('p', 'world-disclaimer', 'AI可能犯错。关键结论请点击来源核对；内容不构成投资建议。'));
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
    const sources = this.briefing!.sources.news.join(' · ') || '新闻源暂不可用';
    footer.append(
      el('span', '', `公开来源：${sources}`),
      el('span', '', '数字由代码计算 · 叙事由证据约束 · 未知明确标注'),
    );
    return footer;
  }

  public destroy(): void {
    this.controller?.abort();
    if (this.refreshTimer !== null) window.clearInterval(this.refreshTimer);
  }
}
