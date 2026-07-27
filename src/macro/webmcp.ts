import type { WorldBriefing } from '@/services/macro-client';

interface WebMcpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  execute: (input: Record<string, unknown>) => unknown | Promise<unknown>;
}

interface ModelContext {
  provideContext(context: { tools: WebMcpTool[] }): void;
}

function modelContext(): ModelContext | null {
  const value = (navigator as Navigator & { modelContext?: ModelContext }).modelContext;
  return value?.provideContext ? value : null;
}

function compactBrief(briefing: WorldBriefing): Record<string, unknown> {
  return {
    generated_at: briefing.generated_at,
    evidence_mode: briefing.evidence_mode,
    headline: briefing.headline,
    question: briefing.deep_brief.question,
    bottom_line: briefing.deep_brief.bottom_line,
    explanation: briefing.deep_brief.sections,
    lead_validation: briefing.lead_validation,
    limitations: briefing.limitations,
  };
}

export function registerWorldStateTools(briefing: WorldBriefing): boolean {
  const context = modelContext();
  if (!context) {
    document.documentElement.dataset.webmcp = 'unsupported';
    return false;
  }

  const marketKeys = briefing.markets.map((market) => market.key);
  const sections = [
    'today',
    'desk',
    'chain',
    'deep',
    'calendar',
    'markets',
    'correlations',
    'topics',
    'perspectives',
    'pipeline',
    'course',
  ];
  const tools: WebMcpTool[] = [
    {
      name: 'worldstate-get-daily-brief',
      description:
        'Read today’s evidence-grounded world and macro explanation, including the causal chain, cross-asset validation, uncertainty and falsifiers.',
      inputSchema: { type: 'object', properties: {}, additionalProperties: false },
      execute: () => compactBrief(briefing),
    },
    {
      name: 'worldstate-explain-market',
      description:
        'Explain one tracked market using its observed move, macro role, current lead event and cross-asset evidence. This does not provide trading advice.',
      inputSchema: {
        type: 'object',
        properties: {
          market: {
            type: 'string',
            enum: marketKeys,
            description: 'Stable market key, such as gold, sp500, us10y, oil or bitcoin.',
          },
        },
        required: ['market'],
        additionalProperties: false,
      },
      execute: ({ market }) => {
        const row = briefing.markets.find((candidate) => candidate.key === market);
        if (!row) throw new Error('Unknown market key');
        return {
          market: row,
          lead_event: briefing.events[0] ?? null,
          macro_chain: briefing.macro_chain,
          validation: briefing.lead_validation,
          limitations: briefing.limitations,
        };
      },
    },
    {
      name: 'worldstate-get-viewpoints',
      description:
        'Read the current institutional, researcher, practitioner, and X viewpoints as testable hypotheses with caveats and suggested validation variables.',
      inputSchema: {
        type: 'object',
        properties: {
          source_class: {
            type: 'string',
            enum: ['all', 'institutional', 'researcher', 'practitioner', 'social'],
          },
        },
        additionalProperties: false,
      },
      execute: ({ source_class }) => ({
        generated_at: briefing.generated_at,
        viewpoints: source_class && source_class !== 'all'
          ? briefing.perspectives.filter((view) => view.source_class === source_class)
          : briefing.perspectives,
        rule: 'Viewpoints are hypotheses, not observed causes. Validate them with independent data and cross-asset prices.',
      }),
    },
    {
      name: 'worldstate-get-research-calls',
      description:
        'Inspect credential-free research source operations, including Agent Reach X call success, item counts, bounded durations, and cache state.',
      inputSchema: { type: 'object', properties: {}, additionalProperties: false },
      execute: () => ({
        generated_at: briefing.generated_at,
        agent_reach_x: briefing.integrations.agent_reach_x,
        official_x: briefing.integrations.x,
        clawfeed: briefing.integrations.clawfeed,
        security:
          'Credentials stay in the local backend and are never included in this tool response.',
      }),
    },
    {
      name: 'worldstate-get-calendar',
      description:
        'Read upcoming official macro releases and central-bank meetings, including source provenance, impact, event questions, two directional scenarios, and first confirmation assets.',
      inputSchema: {
        type: 'object',
        properties: {
          impact: {
            type: 'string',
            enum: ['all', 'high', 'medium'],
          },
        },
        additionalProperties: false,
      },
      execute: ({ impact }) => ({
        generated_at: briefing.generated_at,
        status: briefing.calendar.status,
        method: briefing.calendar.method,
        events:
          impact && impact !== 'all'
            ? briefing.calendar.events.filter((event) => event.impact === impact)
            : briefing.calendar.events,
      }),
    },
    {
      name: 'worldstate-get-market-system',
      description:
        'Read the cross-asset market-implied regimes, breadth, confirmations, divergences, multi-horizon returns, and rolling relationships. Correlation is explicitly not treated as causation.',
      inputSchema: { type: 'object', properties: {}, additionalProperties: false },
      execute: () => ({
        generated_at: briefing.generated_at,
        market_system: briefing.market_system,
        topics: briefing.topics,
        limitations: briefing.limitations,
      }),
    },
    {
      name: 'worldstate-show-section',
      description:
        'Bring a visible World State Terminal section into view so the user and agent can inspect the same evidence together.',
      inputSchema: {
        type: 'object',
        properties: {
          section: {
            type: 'string',
            enum: sections,
            description:
              'One of today, desk, chain, deep, calendar, markets, correlations, topics, perspectives, pipeline, or course.',
          },
        },
        required: ['section'],
        additionalProperties: false,
      },
      execute: ({ section }) => {
        if (typeof section !== 'string' || !sections.includes(section)) {
          throw new Error('Unknown section');
        }
        const target = document.getElementById(section);
        if (!target) {
          const viewBySection: Record<string, string> = {
            today: 'overview',
            desk: 'overview',
            chain: 'events',
            deep: 'events',
            calendar: 'calendar',
            markets: 'markets',
            correlations: 'markets',
            topics: 'themes',
            perspectives: 'signals',
            pipeline: 'signals',
            course: 'library',
          };
          const url = new URL(window.location.href);
          url.searchParams.set('view', viewBySection[section] ?? 'overview');
          url.hash = section;
          window.location.href = url.toString();
          return { shown: section, navigated: true };
        }
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return {
          shown: section,
          navigated: false,
          title: target.querySelector('h2')?.textContent ?? section,
        };
      },
    },
  ];

  try {
    context.provideContext({ tools });
    document.documentElement.dataset.webmcp = 'registered';
    return true;
  } catch {
    document.documentElement.dataset.webmcp = 'failed';
    return false;
  }
}
