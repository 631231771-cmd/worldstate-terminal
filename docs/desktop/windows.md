# Windows desktop

There are three supported launcher layers and no parallel legacy launcher:

- Desktop daily entry: `C:\Users\Administrator\Desktop\WorldState Terminal.bat`
- Repository one-click entry: `WorldStateApp.bat`
- Maintenance and diagnostics: `WorldState.bat <command>`

The desktop entry only validates the repository path and delegates to
`WorldStateApp.bat`. The repository entry prefers an available Tauri build and
otherwise starts the local Research API and Terminal UI through the BAT path.
The BAT path migrates the database, writes logs under `.runtime/logs`, and opens
the application.

Supported maintenance commands are:

```powershell
.\WorldState.bat start
.\WorldState.bat stop
.\WorldState.bat status
.\WorldState.bat doctor
.\WorldState.bat migrate
.\WorldState.bat bootstrap
.\WorldState.bat logs
```

`status` reports the detected PID and port for the API/UI, the database health,
and both BAT and desktop log locations. `stop` stops only API/UI processes
managed or safely adopted by the BAT launcher; exit the Tauri window normally
to stop its child API.

The Tauri shell is under `apps/desktop-tauri`:

```powershell
npm ci --prefix apps/terminal-ui
npm ci --prefix apps/desktop-tauri
npm run check --prefix apps/desktop-tauri
npm run build --prefix apps/desktop-tauri
```

Building requires the stable Rust toolchain and the Windows WebView2/build
toolchain. The current desktop bundle carries the service resources but still
expects a compatible Python 3.12 runtime/environment; therefore the BAT launcher
is the fallback rather than a second product entry. A fully self-contained
signed installer needs a frozen Python sidecar and code-signing and is
intentionally listed as remaining packaging work.

Local data is never written into the installation directory. Tauri uses the
operating-system app-data/log directories and Windows Credential Manager for
supported API secrets.

The confirmed obsolete PySide shortcut and duplicate desktop BAT were archived
under `WorldState Launcher Archive 2026-07-31` on the desktop. Do not run
launchers from that archive.
