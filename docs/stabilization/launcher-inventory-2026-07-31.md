# WorldState launcher inventory — 2026-07-31

This is the pre-cleanup inventory. Hashes and timestamps describe files before
the launcher consolidation changes.

## Scanned locations

- `C:\Users\Administrator\Desktop`
- `C:\Users\Public\Desktop`
- `C:\Users\Administrator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs`
- `C:\Users\Administrator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`
- `F:\Code\world\worldstate-terminal`, including `scripts` and `apps`
- Windows scheduled tasks, related running processes, and listeners on ports
  8000 and 4173

No matching scheduled task, Startup entry, Start Menu entry, Public Desktop
entry, related residual process, or listener on port 8000/4173 was found.

## Candidate summary

| Path | Type | Size | SHA256 | Target / command | Dependencies | Runnable | Classification | Action |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| `C:\Users\Administrator\Desktop\WorldState Terminal.bat` | BAT | 111 | `92E9DB26094A166E502E233A0758FA1811CA275FBA2C73E052A7C72491216FBD` | `WorldStateApp.bat` | Python/Node fallback; Tauri preferred | Yes | A — official desktop entry | Retain and harden |
| `C:\Users\Administrator\Desktop\打开世界状态终端.bat` | BAT | 135 | `FE95C64C41291700794ACC5C78A27D106CB3BCEA32C54A195258EBCC4D950507` | `WorldState.bat start` | Python, Node | Yes | D — duplicate | Archive |
| `C:\Users\Administrator\Desktop\世界状态终端.lnk` | LNK | 993 | `7FED8F6E14A12FDBEB12225659A7DD407F7B3E4737EC020A394105363D78F38A` | `pythonw.exe scripts\worldstate_desktop.py` | Python, legacy PySide6 | No: script and icon target missing | C — confirmed legacy | Archive |
| `F:\Code\world\worldstate-terminal\WorldStateApp.bat` | BAT | 477 | `E09ABF68FBCB059A9F5267C9F068B1CC56F5C899976AAEFCDC66EF7A1E60AD13` | Tauri build, then BAT fallback | Python, Node, optional Tauri | Yes | A — repository official entry | Retain and consolidate |
| `F:\Code\world\worldstate-terminal\WorldState.bat` | BAT | 285 | `B3790F275ADEFF63A5905E65A468D9297C5D1D56175C4B5D8EE7F1EE51A0FB20` | `scripts\worldstate.ps1 <command>` | PowerShell, Python, Node | Yes | B — maintenance entry | Retain |
| `F:\Code\world\worldstate-terminal\scripts\worldstate.ps1` | PowerShell | 9,720 | `0D08888660E31E563FCD055CBD37E2F3839E713A263E238B0BDE4DE0F731C1A3` | API/UI/migration/diagnostics | Python, Node | Yes | B — implementation helper | Retain under `scripts` |
| `F:\Code\world\worldstate-terminal\apps\desktop-tauri\src-tauri\target\debug\worldstate-terminal.exe` | EXE | 15,119,360 | `EECBD526D2B8FFCA4BD9072717155E73736679E9DD2F40884C80816CAF486AB5` | Embedded UI and Research API launcher | Tauri and external Python runtime | Pending clean-start check | B — development build artifact | Retain outside Git |

## Full shortcut resolution

`世界状态终端.lnk` resolves to:

- Target: `F:\Tools\Python\pythonw.exe` — exists.
- Arguments:
  `"F:\Code\world\worldstate-terminal\scripts\worldstate_desktop.py"` — missing.
- Start in: `F:\Code\world\worldstate-terminal`.
- Icon:
  `F:\Code\world\worldstate-terminal\src-tauri\icons\icon.ico,0` — missing.

The repository contains no active `scripts\worldstate_desktop.py` and no
PySide6 dependency. The shortcut is therefore a confirmed obsolete PySide
launcher rather than an uncertain user file.

## Script responsibilities after consolidation

- Desktop: `WorldState Terminal.bat` only validates the repository path and
  delegates to `WorldStateApp.bat`.
- Repository one-click entry: `WorldStateApp.bat` selects the available Tauri
  development build or the verified BAT fallback.
- Maintenance: `WorldState.bat <command>` delegates to the single implementation
  at `scripts\worldstate.ps1`.

The machine-readable inventory next to this file contains every requested
field, including timestamps, working directories, ports, runtime dependencies,
legacy flags, and recommendations.
