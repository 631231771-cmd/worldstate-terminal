export type ResearchJournalPhase = 'pre_event' | 'post_event';
export type ResearchJournalStatus = 'draft' | 'monitoring' | 'reviewed' | 'invalidated';

export interface ResearchJournalDraft {
  phase: ResearchJournalPhase;
  status: ResearchJournalStatus;
  centralQuestion: string;
  primaryHypothesis: string;
  alternativeHypothesis: string;
  expectedTransmission: string;
  disconfirmingEvidence: string;
  unknowns: string;
  nextCheckAt: string;
  actual: string;
  forecast: string;
  previous: string;
  outcomeReview: string;
  lesson: string;
}

export interface ResearchJournalRevision {
  id: string;
  createdAt: string;
  changedFields: Array<keyof ResearchJournalDraft>;
  snapshot: ResearchJournalDraft;
}

export interface ResearchJournalEntry {
  eventId: string;
  eventTitle: string;
  scheduledAt: string;
  createdAt: string;
  updatedAt: string;
  current: ResearchJournalDraft;
  revisions: ResearchJournalRevision[];
}

const STORAGE_KEY = 'worldstate.event-research-journal.v1';
const MAX_ENTRIES = 100;
const MAX_REVISIONS = 100;
const DRAFT_FIELDS: Array<keyof ResearchJournalDraft> = [
  'phase',
  'status',
  'centralQuestion',
  'primaryHypothesis',
  'alternativeHypothesis',
  'expectedTransmission',
  'disconfirmingEvidence',
  'unknowns',
  'nextCheckAt',
  'actual',
  'forecast',
  'previous',
  'outcomeReview',
  'lesson',
];

function storageBackend(): Storage {
  return new URL(window.location.href).searchParams.get('journalTest') === '1'
    ? sessionStorage
    : localStorage;
}

function storageAvailable(): boolean {
  try {
    const key = `${STORAGE_KEY}.probe`;
    const storage = storageBackend();
    storage.setItem(key, '1');
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

function isDraft(value: unknown): value is ResearchJournalDraft {
  if (!value || typeof value !== 'object') return false;
  const draft = value as Partial<ResearchJournalDraft>;
  return DRAFT_FIELDS.every((field) => typeof draft[field] === 'string');
}

function isRevision(value: unknown): value is ResearchJournalRevision {
  if (!value || typeof value !== 'object') return false;
  const revision = value as Partial<ResearchJournalRevision>;
  return typeof revision.id === 'string'
    && typeof revision.createdAt === 'string'
    && Array.isArray(revision.changedFields)
    && revision.changedFields.every((field) => DRAFT_FIELDS.includes(field))
    && isDraft(revision.snapshot);
}

function isEntry(value: unknown): value is ResearchJournalEntry {
  if (!value || typeof value !== 'object') return false;
  const entry = value as Partial<ResearchJournalEntry>;
  return typeof entry.eventId === 'string'
    && typeof entry.eventTitle === 'string'
    && typeof entry.scheduledAt === 'string'
    && typeof entry.createdAt === 'string'
    && typeof entry.updatedAt === 'string'
    && isDraft(entry.current)
    && Array.isArray(entry.revisions)
    && entry.revisions.every(isRevision);
}

export function loadResearchJournal(): ResearchJournalEntry[] {
  if (!storageAvailable()) return [];
  try {
    const raw = storageBackend().getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isEntry);
  } catch {
    return [];
  }
}

function writeResearchJournal(entries: ResearchJournalEntry[]): void {
  if (!storageAvailable()) throw new Error('浏览器本地存储不可用');
  storageBackend().setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
}

export function getResearchJournalEntry(eventId: string): ResearchJournalEntry | null {
  return loadResearchJournal().find((entry) => entry.eventId === eventId) ?? null;
}

export function saveResearchJournalEntry(
  event: { id: string; title: string; scheduledAt: string },
  draft: ResearchJournalDraft,
): ResearchJournalEntry {
  const entries = loadResearchJournal();
  const existingIndex = entries.findIndex((entry) => entry.eventId === event.id);
  const now = new Date().toISOString();
  const previous = existingIndex >= 0 ? entries[existingIndex] : null;
  const changedFields = previous
    ? DRAFT_FIELDS.filter((field) => previous.current[field] !== draft[field])
    : [...DRAFT_FIELDS];
  if (previous && changedFields.length === 0) return previous;
  const revision: ResearchJournalRevision = {
    id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
    createdAt: now,
    changedFields,
    snapshot: { ...draft },
  };
  const entry: ResearchJournalEntry = {
    eventId: event.id,
    eventTitle: event.title,
    scheduledAt: event.scheduledAt,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
    current: { ...draft },
    revisions: [...(previous?.revisions ?? []), revision].slice(-MAX_REVISIONS),
  };
  if (existingIndex >= 0) entries.splice(existingIndex, 1);
  entries.unshift(entry);
  writeResearchJournal(entries);
  return entry;
}

function cleanMarkdown(value: string): string {
  return value.trim() || '尚未填写';
}

export function researchJournalMarkdown(entry: ResearchJournalEntry): string {
  const current = entry.current;
  const history = entry.revisions
    .slice()
    .reverse()
    .map((revision, index) => {
      const changed = revision.changedFields.join(', ');
      return `${index + 1}. ${revision.createdAt} — ${changed || '无字段变化'}`;
    })
    .join('\n');
  return [
    '---',
    `event_id: ${JSON.stringify(entry.eventId)}`,
    `scheduled_at: ${JSON.stringify(entry.scheduledAt)}`,
    `phase: ${current.phase}`,
    `status: ${current.status}`,
    `updated_at: ${entry.updatedAt}`,
    '---',
    '',
    `# ${entry.eventTitle}`,
    '',
    '## 中心问题',
    '',
    cleanMarkdown(current.centralQuestion),
    '',
    '## 主假设',
    '',
    cleanMarkdown(current.primaryHypothesis),
    '',
    '## 替代解释',
    '',
    cleanMarkdown(current.alternativeHypothesis),
    '',
    '## 预期传导',
    '',
    cleanMarkdown(current.expectedTransmission),
    '',
    '## 证伪条件',
    '',
    cleanMarkdown(current.disconfirmingEvidence),
    '',
    '## 仍未知',
    '',
    cleanMarkdown(current.unknowns),
    '',
    '## 公布值',
    '',
    `- Actual: ${cleanMarkdown(current.actual)}`,
    `- Forecast: ${cleanMarkdown(current.forecast)}`,
    `- Previous / Revision: ${cleanMarkdown(current.previous)}`,
    '',
    '## 事件后复盘',
    '',
    cleanMarkdown(current.outcomeReview),
    '',
    '## 可迁移的教训',
    '',
    cleanMarkdown(current.lesson),
    '',
    '## 修订记录',
    '',
    history || '尚无修订',
    '',
    '> 本日志记录当时的判断过程，不构成投资建议。',
    '',
  ].join('\n');
}

export function downloadResearchJournal(entry: ResearchJournalEntry): void {
  const blob = new Blob([researchJournalMarkdown(entry)], {
    type: 'text/markdown;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `worldstate-${entry.eventId.replace(/[^a-z0-9_-]+/gi, '-')}.md`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
