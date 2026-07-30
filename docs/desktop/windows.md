# Windows desktop

The quickest supported path is `WorldStateApp.bat`. It starts the local Research
API and terminal UI, migrates the database, writes logs under `.runtime/logs`
and opens the application. Use `WorldState.bat stop` to stop only processes
started by WorldState.

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
is the verified daily-use path. A fully self-contained signed installer needs a
frozen Python sidecar and code-signing and is intentionally listed as remaining
packaging work.

Local data is never written into the installation directory. Tauri uses the
operating-system app-data/log directories and Windows Credential Manager for
supported API secrets.
