# WorldState launcher cleanup report — 2026-07-31

## Result

Launcher cleanup is complete. The active Desktop now contains one WorldState
entry, the repository contains one one-click entry plus one maintenance entry,
and the two confirmed old Desktop launchers are preserved in a dated archive.
No v0.4 research-method stabilization work was performed.

## Retained

### Desktop official entry

- Path: `C:\Users\Administrator\Desktop\WorldState Terminal.bat`
- Final SHA256:
  `F16DCCB7842B8942CCA86EDB515151EE67BF7AD7531B8891DE58B83F17198671`
- Responsibility: validate
  `F:\Code\world\worldstate-terminal`, then delegate to
  `WorldStateApp.bat`.
- The script contains only ASCII-compatible commands and displays a persistent,
  explicit error if the repository or delegated launch fails.

### Repository official entry

- Path: `F:\Code\world\worldstate-terminal\WorldStateApp.bat`
- Final SHA256:
  `F178988273BC294686EB2564005C5C1EDCF832B552D18FD3AA0143332D17A4EF`
- Responsibility: delegate one-click launch selection to the maintained
  PowerShell implementation. An available Tauri release/debug build is preferred;
  otherwise the verified local API/UI BAT path is used.

### Maintenance entry and implementation

- `WorldState.bat` — SHA256
  `B3790F275ADEFF63A5905E65A468D9297C5D1D56175C4B5D8EE7F1EE51A0FB20`
- `scripts\worldstate.ps1` — SHA256
  `BEFF98534E1809F1F28D181EA56BCA563B3D11B2AAEDDE8F7C6605D6C3EEE2C2`
- Public maintenance commands:
  `start`, `stop`, `status`, `doctor`, `migrate`, `bootstrap`, and `logs`.
- `status` now reports API/UI state, PID, port, BAT log path, desktop log
  path, database status, and methodology version.
- Port collisions report the owning PID and process instead of silently
  starting another service.
- A second launch recognizes an existing repository Tauri process or managed
  API/UI process and does not create duplicates.

### Necessary development artifact

- `apps\desktop-tauri\src-tauri\target\debug\worldstate-terminal.exe`
- Pre-cleanup SHA256:
  `EECBD526D2B8FFCA4BD9072717155E73736679E9DD2F40884C80816CAF486AB5`
- Retained as an ignored development build. It is not represented as a
  self-contained release or committed executable.

## Archived

Archive root:
`C:\Users\Administrator\Desktop\WorldState Launcher Archive 2026-07-31`

| Original path | Archive path | SHA256 | Reason |
| --- | --- | --- | --- |
| `C:\Users\Administrator\Desktop\打开世界状态终端.bat` | `desktop\打开世界状态终端.bat` | `FE95C64C41291700794ACC5C78A27D106CB3BCEA32C54A195258EBCC4D950507` | Duplicate of the maintained BAT start behavior |
| `C:\Users\Administrator\Desktop\世界状态终端.lnk` | `desktop\世界状态终端.lnk` | `7FED8F6E14A12FDBEB12225659A7DD407F7B3E4737EC020A394105363D78F38A` | Broken legacy PySide shortcut; referenced script and icon path are missing |

Both files were copied first, their source/archive SHA256 values were compared,
and only matching copies were moved out of the active Desktop.

## Deleted

No repository launcher was deleted. No unrelated Desktop, Start Menu, Startup,
scheduled-task, process, or user file was deleted.

The active repository already contained only:

- `WorldStateApp.bat`
- `WorldState.bat`
- `scripts\worldstate.ps1`

The legacy `scripts\worldstate_desktop.py` was already absent and had no active
repository reference to remove.

## Unprocessed

There were no uncertain candidates. The `README.txt` and empty source-location
folders in the desktop archive are intentional audit structure, not active
launchers.

## Processes and ports

### Before cleanup

- Port 8000: no listener.
- Port 4173: no listener.
- Related WorldState/World Monitor process: none.
- Matching scheduled task: none.

### Desktop-entry verification

- Tauri PID: `20444`
- API listener PID: `1780` (child of repository virtual-environment Python
  process `18508`)
- Port 8000: WorldState Research API v2, database `ok`.
- UI: embedded Tauri UI.
- Repeating the desktop launch retained exactly one Tauri PID (`20444`).

The automated test terminated the Tauri process directly rather than clicking
its window close control. That forced termination did not run Tauri's graceful
child cleanup and left its verified repository API child; PIDs `1780` and
`18508` were then explicitly stopped after path and parent verification. No
listener remained.

### BAT-entry verification

- Managed Research API PID: `16808`; listener child PID: `12352`; port 8000.
- Managed Terminal UI PID: `30700`; port 4173.
- A second `start` kept the same API/UI process trees and created no duplicate.
- `stop` removed both managed process trees, PID files, and listeners.

### After cleanup and verification

- Port 8000: no listener.
- Port 4173: no listener.
- WorldState PID files: none.
- Active WorldState/World Monitor residual process: none.

## Validation

| Check | Result |
| --- | --- |
| Desktop entry resolves current repository | Passed |
| Desktop entry starts current Tauri build | Passed |
| Duplicate desktop launch protection | Passed |
| `/v2/health` product identity and database | Passed |
| `WorldState.bat doctor` | Passed |
| `WorldState.bat start` | Passed |
| `WorldState.bat status` PID/port/log output | Passed |
| Duplicate BAT start protection | Passed |
| `WorldState.bat stop` | Passed |
| Ports and PID files empty after stop | Passed |
| Inventory JSON parse | Passed |
| Active Desktop has one WorldState launcher | Passed |
| Start Menu/Startup/scheduled-task cleanup | Passed; nothing matched |
| Event Lab browser navigation | Not rerun: the in-app browser blocked localhost navigation by policy |

Both the Tauri and BAT launch paths confirmed a live current Research API and UI
runtime. The UI endpoint became ready through the launcher's own readiness
check. The existing in-app-browser tab could not be reloaded because the browser
surface blocks local addresses; this limitation is reported rather than
misstated as a visual pass.

## Documentation

The following now recommend only the consolidated launch chain:

- `README.md`
- `docs\desktop\windows.md`
- `project-memory\CURRENT.md`
- `docs\migration\final-report.md`

Inventory:

- `docs\stabilization\launcher-inventory-2026-07-31.md`
- `docs\stabilization\launcher-inventory-2026-07-31.json`

The desktop archive contains copies of the inventory, this report, and a restore
README. Git history, `world-monitor-legacy-freeze`, and
`archive/world-monitor-legacy` were not modified.
