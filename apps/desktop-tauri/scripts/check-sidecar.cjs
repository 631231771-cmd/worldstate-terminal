// Do not silently ship an older frozen API beside a newer terminal UI.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const service = path.join(root, 'services/research-api');
const executable = path.join(root, 'apps/desktop-tauri/src-tauri/bin/worldstate-research-api/worldstate-research-api-x86_64-pc-windows-msvc.exe');
if (process.platform === 'win32' && fs.existsSync(executable)) {
  const builtAt = fs.statSync(executable).mtimeMs;
  function sources(directory) {
    return fs.readdirSync(directory, {withFileTypes:true}).flatMap(entry => {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) return entry.name === '__pycache__' ? [] : sources(file);
      return /\.(py|yaml)$/.test(entry.name) ? [file] : [];
    });
  }
  const inputs = [...sources(path.join(service, 'src')), ...sources(path.join(service, 'migrations')),
    ...sources(path.join(root, 'data/macro')),
    path.join(root, 'scripts/build-research-sidecar.ps1'),
    ...['pyproject.toml', 'uv.lock', 'alembic.ini'].map(name => path.join(service, name))];
  if (inputs.some(file => fs.statSync(file).mtimeMs > builtAt)) {
    console.error('The bundled Research API is older than its source. Run scripts/build-research-sidecar.ps1 before building the desktop.');
    process.exit(1);
  }
}
