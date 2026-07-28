import assert from 'node:assert/strict';
import test from 'node:test';

import {
  loadResearchJournal,
  researchJournalMarkdown,
  type ResearchJournalDraft,
  saveResearchJournalEntry,
} from '../src/macro/research-journal.ts';

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

const storage = new MemoryStorage();
Object.defineProperty(globalThis, 'window', {
  configurable: true,
  value: { location: { href: 'http://127.0.0.1:4173/?journalTest=1' } },
});
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: new MemoryStorage(),
});
Object.defineProperty(globalThis, 'sessionStorage', {
  configurable: true,
  value: storage,
});

const firstDraft: ResearchJournalDraft = {
  phase: 'pre_event',
  status: 'draft',
  centralQuestion: '市场会怎样理解这次事件？',
  primaryHypothesis: '利率与美元先反应。',
  alternativeHypothesis: '价格变化来自风险偏好。',
  expectedTransmission: '利率 → 美元 → 黄金',
  disconfirmingEvidence: '第二市场不确认。',
  unknowns: '实际值尚未公布。',
  nextCheckAt: '2026-07-30T03:30',
  actual: '',
  forecast: '',
  previous: '',
  outcomeReview: '',
  lesson: '',
};

test('research journal appends meaningful revisions without duplicating unchanged saves', () => {
  const event = {
    id: 'fomc-2026-07',
    title: 'FOMC 利率决议',
    scheduledAt: '2026-07-30T02:00:00+08:00',
  };
  const first = saveResearchJournalEntry(event, firstDraft);
  const unchanged = saveResearchJournalEntry(event, firstDraft);
  const revised = saveResearchJournalEntry(event, {
    ...firstDraft,
    status: 'monitoring',
    lesson: '等待第二个独立市场确认。',
  });

  assert.equal(first.revisions.length, 1);
  assert.equal(unchanged.revisions.length, 1);
  assert.equal(revised.revisions.length, 2);
  assert.deepEqual(revised.revisions[1]?.changedFields, ['status', 'lesson']);
  assert.equal(loadResearchJournal().length, 1);

  const markdown = researchJournalMarkdown(revised);
  assert.match(markdown, /## 替代解释/);
  assert.match(markdown, /## 证伪条件/);
  assert.match(markdown, /等待第二个独立市场确认/);
});
