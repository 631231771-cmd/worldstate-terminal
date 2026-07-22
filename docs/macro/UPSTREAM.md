# Upstream record

## Pinned source

- Project: World Monitor
- Repository: `https://github.com/koala73/worldmonitor.git`
- Pinned commit: `7fe22e47dc90ee2693d0071323561e5bbffe5c42`
- Commit subject: `Update blog post to 6 dashboards, fix variants count, and add Energy … (#5408)`
- Retrieved: 2026-07-22
- Local branch: `feature/world-state-terminal`
- Local remote: `upstream`

The project must remain based on this commit until a deliberate upstream-sync
change records a new pin, migration notes, test results, and license review.

## Attribution and license

The pinned project declares `AGPL-3.0-only` in `package.json` and includes the
World Monitor copyright and GNU Affero General Public License text in `LICENSE`.
Those files and notices must not be removed or relabeled.

## Upstream synchronization policy

1. Fetch upstream without overwriting local work.
2. Review upstream license and dependency changes first.
3. Re-run the baseline and all existing variant builds.
4. Re-run Macro Engine contracts and point-in-time tests.
5. Update this file, `BASELINE.md`, `THIRD_PARTY.md`, and `CUSTOMIZATIONS.md`.
6. Resolve changes by bounded merge or rebase work; do not rewrite the product as
   an unrelated fork.
