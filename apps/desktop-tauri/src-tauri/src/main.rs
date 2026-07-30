#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use keyring::Entry;
use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent};

const KEYRING_SERVICE: &str = "worldstate-terminal";
const API_URL: &str = "http://127.0.0.1:8000/v2/health";

#[derive(Default)]
struct ResearchApiState {
    child: Mutex<Option<Child>>,
    database_path: Mutex<Option<PathBuf>>,
    log_path: Mutex<Option<PathBuf>>,
}

#[derive(Serialize)]
struct BackendStatus {
    reachable: bool,
    api_url: &'static str,
    database_path: Option<String>,
    log_path: Option<String>,
}

fn development_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap_or_else(|_| Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.."))
}

fn resolve_service_root(app: &AppHandle) -> PathBuf {
    if cfg!(debug_assertions) {
        return development_root().join("services/research-api");
    }
    app.path()
        .resource_dir()
        .map(|path| path.join("services/research-api"))
        .unwrap_or_else(|_| development_root().join("services/research-api"))
}

fn python_command(service_root: &Path) -> PathBuf {
    let bundled = service_root.join(".venv/Scripts/python.exe");
    if bundled.exists() {
        return bundled;
    }
    PathBuf::from("python")
}

fn spawn_research_api(app: &AppHandle, state: &ResearchApiState) -> Result<(), String> {
    let service_root = resolve_service_root(app);
    if !service_root.join("pyproject.toml").exists() {
        return Err(format!(
            "Research API files are missing at {}",
            service_root.display()
        ));
    }
    let data_dir = app.path().app_local_data_dir().map_err(|error| error.to_string())?;
    let log_dir = app.path().app_log_dir().map_err(|error| error.to_string())?;
    fs::create_dir_all(&data_dir).map_err(|error| error.to_string())?;
    fs::create_dir_all(&log_dir).map_err(|error| error.to_string())?;
    let database_path = data_dir.join("worldstate.db");
    let log_path = log_dir.join("research-api.log");
    let database_url = format!(
        "sqlite+aiosqlite:///{}",
        database_path.to_string_lossy().replace('\\', "/")
    );
    let python = python_command(&service_root);

    let migration = Command::new(&python)
        .args(["-m", "worldstate.cli", "migrate"])
        .current_dir(&service_root)
        .env("WORLDSTATE_DATABASE_URL", &database_url)
        .status()
        .map_err(|error| format!("Could not start database migration: {error}"))?;
    if !migration.success() {
        return Err("WorldState database migration failed. Open the desktop log for details.".into());
    }

    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| error.to_string())?;
    let stderr = stdout.try_clone().map_err(|error| error.to_string())?;
    let child = Command::new(&python)
        .args([
            "-m",
            "worldstate.cli",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ])
        .current_dir(&service_root)
        .env("WORLDSTATE_DATABASE_URL", database_url)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|error| format!("Could not start Research API: {error}"))?;

    *state.child.lock().map_err(|_| "Backend state lock failed")? = Some(child);
    *state
        .database_path
        .lock()
        .map_err(|_| "Database state lock failed")? = Some(database_path);
    *state.log_path.lock().map_err(|_| "Log state lock failed")? = Some(log_path);
    Ok(())
}

#[tauri::command]
async fn backend_status(state: tauri::State<'_, ResearchApiState>) -> BackendStatus {
    let reachable = reqwest::get(API_URL)
        .await
        .map(|response| response.status().is_success())
        .unwrap_or(false);
    BackendStatus {
        reachable,
        api_url: API_URL,
        database_path: state
            .database_path
            .lock()
            .ok()
            .and_then(|value| value.as_ref().map(|path| path.display().to_string())),
        log_path: state
            .log_path
            .lock()
            .ok()
            .and_then(|value| value.as_ref().map(|path| path.display().to_string())),
    }
}

#[tauri::command]
fn save_api_secret(name: String, value: String) -> Result<(), String> {
    let allowed = ["OPENAI_API_KEY", "WORLDSTATE_AI_COMPATIBLE_API_KEY"];
    if !allowed.contains(&name.as_str()) {
        return Err("Unsupported secret name".into());
    }
    Entry::new(KEYRING_SERVICE, &name)
        .map_err(|error| error.to_string())?
        .set_password(value.trim())
        .map_err(|error| error.to_string())
}

fn main() {
    let state = ResearchApiState::default();
    let app = tauri::Builder::default()
        .manage(state)
        .invoke_handler(tauri::generate_handler![backend_status, save_api_secret])
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<ResearchApiState>();
            spawn_research_api(&handle, &state).map_err(std::io::Error::other)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build WorldState desktop application");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            let state = handle.state::<ResearchApiState>();
            if let Ok(mut guard) = state.child.lock() {
                if let Some(child) = guard.as_mut() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                *guard = None;
            }
        }
    });
}
