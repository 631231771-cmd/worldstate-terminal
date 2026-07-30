# Third-party notices

WorldState Terminal is licensed under AGPL-3.0-or-later. Package-level notices
remain governed by each dependency's own license.

## Adoption decisions

| Project | License reviewed | Decision |
|---|---|---|
| OpenTerminalUI | MIT | architecture and product-pattern reference; no wholesale fork |
| Macrosynergy | BSD-3-Clause | optional Python dependency behind `MacrosynergyAdapter`; no database/API types exposed |
| OpenBB | AGPL-3.0 | optional isolated provider only; core runs without it |
| Fincept Terminal | AGPL-3.0 or commercial | product research only; no source or visual identity copied |

The exact repositories, audited commits, candidate source files, maintenance
risks and copyright obligations are recorded in
[`docs/macro/open-source-adoption.md`](docs/macro/open-source-adoption.md).

The terminal UI and domain model in this repository were written for
WorldState. Third-party adapters convert external outputs into WorldState
models and may be removed without changing the core database contract.
