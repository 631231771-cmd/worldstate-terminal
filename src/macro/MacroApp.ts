import {
  MacroChangesPanel,
  MacroRegimePanel,
  MacroSeriesExplorerPanel,
  MacroSystemStatusPanel,
  MacroWorldStatePanel,
} from './MacroPanels';
import { initI18n } from '@/services/i18n';
import type { MacroSnapshot } from '@/services/macro-client';
import { macroCopy } from './i18n';
import './macro-terminal.css';

export class MacroApp {
  private readonly root: HTMLElement;
  private panels: Array<{ getElement(): HTMLElement; start(): void; destroy(): void }> = [];
  private snapshotListener: ((event: Event) => void) | null = null;

  constructor(rootId: string) {
    const root = document.getElementById(rootId);
    if (!root) throw new Error(`Missing application root #${rootId}`);
    this.root = root;
  }

  public async init(): Promise<void> {
    this.applyDefaultLanguage();
    await initI18n();
    document.title = macroCopy().title;
    this.render();
  }

  private applyDefaultLanguage(): void {
    const url = new URL(window.location.href);
    if (url.searchParams.has('lang')) return;
    let hasExplicitLocale = false;
    try {
      hasExplicitLocale = Boolean(localStorage.getItem('wm-locale-explicit'));
    } catch {
      // The query default below remains usable when storage is unavailable.
    }
    if (!hasExplicitLocale) {
      url.searchParams.set('lang', 'zh');
      history.replaceState(history.state, '', url);
    }
  }

  private render(): void {
    const copy = macroCopy();
    const shell = document.createElement('main');
    shell.className = 'macro-shell';
    const header = document.createElement('header');
    header.className = 'macro-header';
    const identity = document.createElement('div');
    const title = document.createElement('h1');
    title.textContent = copy.title;
    const subtitle = document.createElement('p');
    subtitle.textContent = copy.subtitle;
    identity.append(title, subtitle);

    const actions = document.createElement('div');
    actions.className = 'macro-header-actions';
    const mode = document.createElement('span');
    mode.className = 'macro-global-mode macro-mode-empty';
    mode.textContent = 'EMPTY';
    mode.title = copy.initializing;
    const language = document.createElement('button');
    language.type = 'button';
    language.className = 'macro-language-button';
    language.textContent = copy.language;
    language.addEventListener('click', () => {
      const url = new URL(window.location.href);
      url.searchParams.set('lang', document.documentElement.lang.startsWith('zh') ? 'en' : 'zh');
      window.location.href = url.toString();
    });
    actions.append(mode, language);
    header.append(identity, actions);

    const grid = document.createElement('section');
    grid.className = 'macro-grid panels-grid';
    grid.id = 'panelsGrid';
    this.panels = [
      new MacroWorldStatePanel(),
      new MacroChangesPanel(),
      new MacroRegimePanel(),
      new MacroSeriesExplorerPanel(),
      new MacroSystemStatusPanel(),
    ];
    for (const panel of this.panels) grid.appendChild(panel.getElement());
    shell.append(header, grid);
    this.root.replaceChildren(shell);

    this.snapshotListener = (event: Event) => {
      const snapshot = (event as CustomEvent<MacroSnapshot>).detail;
      mode.textContent = snapshot.mode;
      mode.className = `macro-global-mode macro-mode-${snapshot.mode.toLowerCase()}`;
      mode.title = snapshot.mode === 'DEMO' ? copy.demoNotice
        : snapshot.mode === 'STALE' ? copy.staleNotice
          : snapshot.mode === 'EMPTY' ? copy.emptyNotice : copy.liveNotice;
    };
    window.addEventListener('worldstate:snapshot', this.snapshotListener);
    for (const panel of this.panels) panel.start();
  }

  public destroy(): void {
    if (this.snapshotListener) {
      window.removeEventListener('worldstate:snapshot', this.snapshotListener);
    }
    for (const panel of this.panels) panel.destroy();
    this.panels = [];
  }
}

