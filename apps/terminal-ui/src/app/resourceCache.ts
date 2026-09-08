/** Only successful observed read projections enter this cache. Never a research input. */
export const CACHE_VERSION = 'research-terminal-2';
export interface CachedRead<T> { value: T; savedAt: string; }
export interface CacheStorage { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void; }
export function readKey(scope: string, key: string) { return `worldstate.read.${CACHE_VERSION}.${scope}.observed.${key}`; }
export function isObserved(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const row = value as { data_mode?: string; event?: { data_mode?: string } };
  const hasFixture = (node: unknown): boolean => {
    if (!node || typeof node !== 'object') return false;
    const fields = node as Record<string, unknown>;
    return fields.data_mode === 'fixture' || fields.is_fixture === true || Object.values(fields).some(hasFixture);
  };
  return (row.data_mode ?? row.event?.data_mode) === 'observed' && !hasFixture(value);
}
export function readCached<T>(storage: CacheStorage, scope: string, key: string): CachedRead<T> | null {
  try {
    const raw = storage.getItem(readKey(scope, key));
    if (!raw) return null;
    const item = JSON.parse(raw) as CachedRead<T>;
    return isObserved(item.value) && Number.isFinite(Date.parse(item.savedAt)) ? item : null;
  } catch { return null; }
}
export function saveCached<T>(storage: CacheStorage, scope: string, key: string, value: T): CachedRead<T> {
  if (!isObserved(value)) throw new Error('研究视图的数据模式不匹配，已保留上一份结果。');
  const item = { value, savedAt: new Date().toISOString() };
  try {
    const serialized = JSON.stringify(item);
    if (serialized.length < 1_500_000) storage.setItem(readKey(scope, key), serialized);
  } catch { /* Storage can be full or unavailable; the in-memory view stays usable. */ }
  return item;
}
