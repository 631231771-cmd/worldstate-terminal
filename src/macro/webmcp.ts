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
  const sections = ['today', 'chain', 'deep', 'perspectives', 'events', 'markets', 'course'];
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
              'One of today, chain, deep, perspectives, events, markets, or course.',
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
        if (!target) throw new Error('Section is not available');
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return { shown: section, title: target.querySelector('h2')?.textContent ?? section };
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
