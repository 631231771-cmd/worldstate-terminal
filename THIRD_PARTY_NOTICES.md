# Third-party notices

This file records third-party code and optional dependencies specifically
reviewed for the WorldState macro-event work. It supplements
`docs/macro/THIRD_PARTY.md`.

## OpenTerminalUI

- Repository: <https://github.com/Hitheshkaranth/OpenTerminalUI>
- Reviewed commit: `fc16fd646405aec7a5525387be89c0cb376137c5`
- License: MIT
- Copyright: Copyright (c) 2026 OpenTerminalUI Contributors
- Use in WorldState: architectural reference only as of 2026-07-30. No source
  file has been copied.

The MIT license requires its copyright and permission notice to be retained in
copies or substantial portions of the software. If source is copied later, the
full license from the reviewed commit must be included.

## Macrosynergy

- Repository: <https://github.com/macrosynergy/macrosynergy>
- Reviewed commit: `d21d6ab0d83d1c597a5bd2355b8d66896a4a8bb6`
- License: BSD 3-Clause
- Copyright: Copyright (c) 2023, Macrosynergy
- Use in WorldState: optional dependency behind an adapter; not required for
  the base CPI Event Lab.

Redistributions must retain the BSD copyright notice, conditions, and
disclaimer. Neither Macrosynergy nor its contributors may be used to endorse
WorldState without prior permission.

## OpenBB

- Repository: <https://github.com/OpenBB-finance/OpenBB>
- Reviewed commit: `3e071fcc2cd9f891cac6040ae60296dba76dab46`
- License: GNU Affero General Public License v3.0
- Copyright: Copyright (c) 2021-2025 OpenBB Inc.
- Use in WorldState: optional, isolated gateway only. No OpenBB source is
  copied into the WorldState core.

OpenBB remains disabled unless separately installed and configured. Bundling,
modification, network deployment, or distribution requires AGPL review.

## Fincept Terminal

- Repository: <https://github.com/Fincept-Corporation/FinceptTerminal>
- Reviewed commit: `823f63848084f3869e4c9a487663f41f44d55989`
- License: AGPL-3.0 or Fincept commercial license
- Copyright: Copyright (C) 2025-2026 Fincept Corporation
- Use in WorldState: product research only. No code, UI, assets, or visual
  identity are copied.

Fincept's repository states that business or internal-company use requires a
commercial license. WorldState does not include or derive from Fincept.
