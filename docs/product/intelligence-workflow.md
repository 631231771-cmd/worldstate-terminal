# WorldState — Intelligence workflow checkpoint

Date: 2026-09-07. Branch: `feature/v0.7-terminal-rebuild`.
Baseline inspected: `f30ae84f4a834fce9f1b386f73cfadd413af4016`.

## Product diagnosis from the running application

The previous first screen prioritized eight generic state scores, while the event and market questions sat below them. CPI expectations, actuals and surprise required reading three separate tables. Market drilldown ended at a chart with passive concept chips. Research opened an empty thesis form. A projection rejection replaced the whole screen; successful projections were not restored after reopening. The generated page timestamp could look current while market observations were weeks old.

## New loop

Radar → selected market → competing pathways and cross-asset direction checks → event → expectations/actuals → reaction → validated research → memory.

Primary navigation is 雷达 / 事件台 / 市场脉络 / 研究记忆. Global macro remains inside market context. Data Sources and Methods remain accessible from tools, not primary navigation. Old route aliases remain usable, and hash/back navigation now updates the application.

The old `TodayBoard.tsx` is removed. Research engines, database models, migrations and `/v2` endpoints are not replaced. Existing consensus/minute import and detailed Event Lab remain accessible.

## Truthfulness boundaries

- Radar pathway text is a fixed conditional observation guide, **not** generated event attribution. Oil movement does not prove a geopolitical/supply event.
- Direction checks require observed, fresh daily readings with the same observation date and frequency. Yield checks require bp, not Treasury-futures percentage prices. Different market closing times still limit comparability. There is no invented significance threshold or lead/lag claim.
- Stale/missing/unequal-frequency readings are unconfirmed. The current local dataset is stale; the product says it cannot explain a move happening now.
- The event comparison renders existing backend surprise results. Threshold-scaled values remain separate from Z-scores. No frontend financial calculation replaces the engine.
- Research reading uses only validated claims belonging to the selected run; a historical response for a different run is rejected. Detailed statistics stay behind disclosure.
- Successful observed projections alone enter a versioned, API-origin-scoped local cache. Fixture responses, including nested fixture data, are rejected. The cache is never used as analysis input. Offline data retains source/observation timestamps and a refresh-failure message.
- No release, consensus, or market import was submitted while testing. No paid data was downloaded. The production runtime DB remains `.runtime/worldstate.db`.

## Verification

- Backend: 221 tests passed; Ruff and strict mypy passed (120 source files). Existing backend test warnings: deprecated TestClient dependency and local pytest cache permission.
- Frontend: build/typecheck and 10 policy tests passed. Browser regression covers radar/learning, market/source drilldown, country drilldown, merged event, consensus modal, minute import entry, memory/back navigation, partial failure, offline reopen, fixture rejection, delayed response races, validated claim/history reading and 1440/1920 widths.
- E2E responses are synthetic and confined to a disposable browser context. They do not constitute live-provider validation. `npm run test:e2e --prefix apps/terminal-ui` requires Playwright Chromium (Edge is used on Windows).
- Rust: fmt/check and eight tests passed. Production-like no-bundle build succeeded. Actual Windows window was opened and verified on local data for Radar, CPI comparison/missing reaction, and Markets. Remaining final-build checks are tracked in CURRENT.md.
- Tauri resources are now an explicit source/migration/config allowlist plus the existing frozen sidecar, not the entire backend development directory. This fixes cache traversal failures and avoids including local virtual environments/caches by directory recursion.

## Remaining acceptance work

Do not call this a live intelligence terminal yet: current daily data is old and CPI minute data is absent. The UI has an operational import path but no new real event-chain run. Continue validating final desktop build, pre-release guides, original research tools and current-data operations before declaring the user's full product objective achieved.
