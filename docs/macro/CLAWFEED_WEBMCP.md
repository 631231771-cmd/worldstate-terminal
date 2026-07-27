# ClawFeed and WebMCP integration

Status: implemented as optional, low-coupling integrations.

## Why these projects are useful

[ClawFeed](https://github.com/lvy010/clawfeed) contributes an editorial model:
the information pool can grow while the final daily edition stays short and
selective. World State Terminal applies that rule to its built-in deep brief:
one question, one bottom line, and five sections covering fact, mechanism,
cross-asset evidence, competing explanations, and what to watch.

[WebMCP](https://github.com/lvy010/webmcp) is an API proposal rather than a
package to install. World State Terminal feature-detects
`navigator.modelContext` and, when the browser supports it, exposes three
structured page tools:

- `worldstate-get-daily-brief`
- `worldstate-explain-market`
- `worldstate-show-section`

The tools read the same evidence visible to the user. The last tool only scrolls
the visible page. They do not change research data, place trades, read cookies,
or expose provider credentials.

## Optional external ClawFeed service

The built-in editorial brief works without another service. To additionally
show editions from a separately running ClawFeed instance, edit
`.runtime/worldstate.env`:

```text
MACRO_CLAWFEED_URL=http://127.0.0.1:8767
```

Then restart World State Terminal. The backend reads at most three daily
editions from ClawFeed's public `GET /api/digests` endpoint, strips markup,
truncates untrusted text, and treats those editions as external summaries rather
than verified facts. Authentication cookies and API keys are not required for
this read-only path.

ClawFeed is not bundled into the desktop launcher. Bundling it would add a
second server, SQLite database, OAuth flow, and port lifecycle while still
requiring a separate collection agent for many sources. Keeping it optional
preserves one-click startup and lets an existing self-hosted instance be reused.

## Compatibility and attribution

- ClawFeed interface reviewed at commit
  `38b43f0c3d5c781acbc3173a3a4a47f480cb18a5` (MIT).
- WebMCP proposal reviewed at commit
  `971aa24aea2afd865ca8607ba79a486fc7429360` (W3C Software and Document
  License).
- The adapters and page tools in this repository are original implementation;
  no upstream source files are vendored.
- Browsers without `navigator.modelContext` keep the complete normal UI. WebMCP
  is progressive enhancement, not a runtime dependency.
