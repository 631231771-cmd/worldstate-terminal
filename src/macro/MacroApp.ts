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
    this.prepareDocument();
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

    const workspace = el('div', 'world-workspace');
    const editorial = el('div', 'world-editorial-column');
    editorial.append(
      this.renderHero(),
      this.renderMacroChain(),
      this.renderDeepBrief(),
      this.renderPerspectives(),
      this.renderEvents(),
      this.renderValidation(),
      this.renderMarketStrip(),
      this.renderLesson(),
      this.renderCurriculum(),
      this.renderMacroFoundation(),
    );
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
    const navItems: Array<readonly [string, string]> = [
      ['#today', '今日简报'],
      ['#chain', '宏观链条'],
      ['#deep', '深度解读'],
      ['#perspectives', '观点实验室'],
      ['#course', '课程路径'],
    ];
    for (const [href, label] of navItems) {
      const link = el('a', '', label);
      link.href = href;
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

  private renderMarketTicker(): HTMLElement {
    const ticker = el('section', 'world-ticker');
    ticker.setAttribute('aria-label', '全球市场速览');
    for (const market of this.briefing!.markets) {
      const item = el('div', `world-ticker-item world-move-${market.direction}`);
      const change =
        market.change_percent === undefined
          ? '待更新'
          : `${market.change_percent >= 0 ? '+' : ''}${market.change_percent.toFixed(2)}%`;
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

  private renderPerspectives(): HTMLElement {
    const briefing = this.briefing!;
    const section = el('section', 'world-section world-perspectives');
    section.id = 'perspectives';
    const heading = el('div', 'world-section-heading');
    heading.append(
      el('div', 'world-section-index', '03 / VIEWPOINT LAB'),
      el('h2', '', '观点不是答案，而是可以被检验的假设'),
      el('p', '', '机构研究负责机制，市场作者负责提出线索；每一条都要翻译成数据与价格。'),
    );
    section.appendChild(heading);

    const xState = briefing.integrations.x;
    const notice = el('div', `world-x-notice ${xState.configured ? 'is-connected' : ''}`);
    notice.append(
      el('strong', '', xState.configured ? `X 官方接口已连接 · 今日 ${xState.items} 条` : 'X 官方接口尚未连接'),
      el(
        'p',
        '',
        xState.configured
          ? 'X 内容只作为实时线索，仍需原始数据和跨资产价格确认。'
          : '公开机构与 Newsletter 仍会每日更新。为保护账户，不使用也不保存浏览器 Cookie。',
      ),
    );
    section.appendChild(notice);

    const grid = el('div', 'world-perspective-grid');
    if (!briefing.perspectives.length) {
      grid.appendChild(
        el('p', 'world-empty', '公开观点源本次没有返回内容；事实简报和宏观课程仍可正常使用。'),
      );
    }
    for (const view of briefing.perspectives) {
      const card = el('article', `world-perspective-card is-${view.source_class}`);
      const meta = el('div', 'world-perspective-meta');
      meta.append(
        el('span', 'world-perspective-class', view.source_class_label),
        el('span', '', `${view.source} · ${formatDate(view.published_at, false)}`),
      );
      card.append(
        meta,
        el('h3', '', view.title),
        el('p', 'world-perspective-claim', view.claim),
      );
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
        el('p', 'world-perspective-caveat', `限制：${view.caveat}`),
        externalLink('阅读原文 ↗', view.url, 'world-perspective-link'),
      );
      grid.appendChild(card);
    }
    section.appendChild(grid);
    return section;
  }

  private renderMarketStrip(): HTMLElement {
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
    for (const market of this.briefing!.markets) grid.appendChild(this.marketCard(market));
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
      market.change_percent === undefined ? '数据待更新' : `${market.change_percent >= 0 ? '+' : ''}${market.change_percent.toFixed(2)}%`,
    );
    value.append(price, change);
    card.append(top, value, renderSparkline(market.sparkline, market.direction));
    const explanation = el('p', 'world-market-explanation', market.explanation);
    card.appendChild(explanation);
    const footer = el('div', 'world-market-footer');
    footer.append(
      market.source_url
        ? externalLink(market.source ?? '行情来源', market.source_url)
        : el('span', '', '来源暂不可用'),
    );
    card.appendChild(footer);
    return card;
  }

  private renderEvents(): HTMLElement {
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
    this.briefing!.events.forEach((event) => list.appendChild(this.eventCard(event)));
    section.appendChild(list);
    return section;
  }

  private eventCard(event: WorldEvent): HTMLElement {
    const details = el('details', 'world-event-card');
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
      const welcome = el('div', 'world-tutor-welcome');
      welcome.append(
        el('strong', '', '从一个具体的“为什么”开始'),
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
  }
}
