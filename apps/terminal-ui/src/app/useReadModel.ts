import { useEffect, useRef, useState } from 'preact/hooks';
import { API_BASE, ApiError } from '../api/transport';
import { readCached, saveCached, type CachedRead } from './resourceCache';

const scope = encodeURIComponent(API_BASE || window.location.origin);
const inFlight = new Map<string, Promise<unknown>>();
function storage() { try { return window.localStorage; } catch { return null; } }
export function useReadModel<T>(key: string, loader: () => Promise<T>, enabled = true) {
  const [state, setState] = useState<{ key: string; cached: CachedRead<T> | null }>(() => ({ key, cached: storage() ? readCached<T>(storage()!, scope, key) : null }));
  const [refreshing, setRefreshing] = useState(false);
  const [failure, setFailure] = useState<{ key: string; message: string; technical: string } | null>(null);
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader); loaderRef.current = loader;
  const cached = state.key === key ? state.cached : storage() ? readCached<T>(storage()!, scope, key) : null;
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    setRefreshing(true); setFailure(null);
    let promise = inFlight.get(key) as Promise<T> | undefined;
    if (!promise) {
      promise = loaderRef.current(); inFlight.set(key, promise);
      void promise.finally(() => { if (inFlight.get(key) === promise) inFlight.delete(key); }).catch(() => undefined);
    }
    void promise.then(value => {
      const store = storage();
      const next = saveCached(store ?? { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }, scope, key, value);
      if (active) setState({ key, cached: next });
    }).catch((error: unknown) => {
      if (active) setFailure({ key, message: error instanceof Error ? error.message : '暂时无法刷新', technical: error instanceof ApiError ? error.technicalDetail : String(error) });
    }).finally(() => { if (active) setRefreshing(false); });
    return () => { active = false; };
  }, [key, enabled, nonce]);
  return { data: cached?.value ?? null, savedAt: cached?.savedAt ?? null, refreshing, error: failure?.key === key ? failure : null, refresh: () => setNonce(n => n + 1) };
}
