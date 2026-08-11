#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, OpenOptions};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use keyring::Entry;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, RunEvent};

const KEYRING_SERVICE: &str = "worldstate-terminal";
const API_URL: &str = "http://127.0.0.1:8000/v2/health";
const EXPECTED_PRODUCT: &str = "worldstate-terminal";
const SIDECAR_EXECUTABLE: &str = "worldstate-research-api-x86_64-pc-windows-msvc.exe";
const ALLOWED_SECRET_NAMES: [&str; 6] = [
    "OPENAI_API_KEY",
    "WORLDSTATE_AI_COMPATIBLE_API_KEY",
    "FRED_API_KEY",
    "BLS_API_KEY",
    "TRADING_ECONOMICS_API_KEY",
    "DATABENTO_API_KEY",
];

#[derive(Default)]
struct ResearchApiState {
    child: Mutex<Option<Child>>,
    database_path: Mutex<Option<PathBuf>>,
    log_path: Mutex<Option<PathBuf>>,
    source: Mutex<String>,
}

#[derive(Deserialize)]
struct HealthResponse {
    product: Option<String>,
    api_version: Option<String>,
    ai_provider: Option<String>,
}

#[derive(Serialize)]
struct BackendStatus {
    reachable: bool,
    product_verified: bool,
    api_url: &'static str,
    port: u16,
    child_pid: Option<u32>,
    ai_provider: String,
    database_path: Option<String>,
    log_path: Option<String>,
    source: String,
}

fn health_matches(health: &HealthResponse) -> bool {
    health.product.as_deref() == Some(EXPECTED_PRODUCT)
        && health.api_version.as_deref() == Some("v2")
}

async fn fetch_health() -> Option<HealthResponse> {
    let Ok(response) = reqwest::get(API_URL).await else {
        return None;
    };
    let Ok(health) = response.json::<HealthResponse>().await else {
        return None;
    };
    Some(health)
}

async fn verified_health() -> bool {
    fetch_health()
        .await
        .is_some_and(|health| health_matches(&health))
}

fn secret_environment<'a>(
    openai: Option<&'a str>,
    compatible: Option<&'a str>,
    fred: Option<&'a str>,
    bls: Option<&'a str>,
    trading_economics: Option<&'a str>,
    databento: Option<&'a str>,
) -> Vec<(&'static str, &'a str)> {
    let mut values = Vec::new();
    if let Some(value) = openai {
        values.push(("OPENAI_API_KEY", value));
    }
    if let Some(value) = compatible {
        values.push(("WORLDSTATE_AI_COMPATIBLE_API_KEY", value));
    }
    if let Some(value) = fred {
        values.push(("FRED_API_KEY", value));
    }
    if let Some(value) = bls {
        values.push(("BLS_API_KEY", value));
    }
    if let Some(value) = trading_economics {
        values.push(("TRADING_ECONOMICS_API_KEY", value));
    }
    if let Some(value) = databento {
        values.push(("DATABENTO_API_KEY", value));
    }
    values
}

fn read_secret(name: &str) -> Option<String> {
    Entry::new(KEYRING_SERVICE, name)
        .ok()
        .and_then(|entry| entry.get_password().ok())
        .filter(|value| !value.trim().is_empty())
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

fn resolve_bundled_sidecar(app: &AppHandle) -> Option<PathBuf> {
    if cfg!(debug_assertions) {
        return None;
    }
    app.path()
        .resource_dir()
        .ok()
        .map(|root| {
            root.join("services/research-api-sidecar")
                .join(SIDECAR_EXECUTABLE)
        })
        .filter(|path| path.exists())
}

fn python_command(service_root: &Path) -> PathBuf {
    let bundled = service_root.join(".venv/Scripts/python.exe");
    if bundled.exists() {
        return bundled;
    }
    PathBuf::from("python")
}

fn existing_port_action(port_open: bool, product_verified: bool) -> Result<bool, String> {
    if !port_open {
        return Ok(false);
    }
    if product_verified {
        return Ok(true);
    }
    Err("Port 8000 is occupied by a service that is not a verified WorldState Research API. Stop that service or select a different port before starting the desktop app.".into())
}

fn spawn_research_api(app: &AppHandle, state: &ResearchApiState) -> Result<(), String> {
    let api_address: SocketAddr = "127.0.0.1:8000"
        .parse()
        .map_err(|error| format!("Invalid local API address: {error}"))?;
    let port_open = TcpStream::connect_timeout(&api_address, Duration::from_millis(250)).is_ok();
    let product_verified = port_open && tauri::async_runtime::block_on(verified_health());
    if existing_port_action(port_open, product_verified)? {
        *state
            .source
            .lock()
            .map_err(|_| "Backend state lock failed")? = "existing".into();
        return Ok(());
    }
    let service_root = resolve_service_root(app);
    let bundled_sidecar = resolve_bundled_sidecar(app);
    if bundled_sidecar.is_none() && !service_root.join("pyproject.toml").exists() {
        return Err(format!(
            "Research API files are missing at {}",
            service_root.display()
        ));
    }
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())?;
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|error| error.to_string())?;
    fs::create_dir_all(&data_dir).map_err(|error| error.to_string())?;
    fs::create_dir_all(&log_dir).map_err(|error| error.to_string())?;
    let database_path = data_dir.join("worldstate.db");
    let log_path = log_dir.join("research-api.log");
    let database_url = format!(
        "sqlite+aiosqlite:///{}",
        database_path.to_string_lossy().replace('\\', "/")
    );
    let python = python_command(&service_root);
    let worldstate_root = service_root
        .parent()
        .and_then(Path::parent)
        .unwrap_or_else(|| Path::new(&service_root));
    let python_path = service_root.join("src");
    let openai_secret = read_secret("OPENAI_API_KEY");
    let compatible_secret = read_secret("WORLDSTATE_AI_COMPATIBLE_API_KEY");
    let fred_secret = read_secret("FRED_API_KEY");
    let bls_secret = read_secret("BLS_API_KEY");
    let trading_economics_secret = read_secret("TRADING_ECONOMICS_API_KEY");
    let databento_secret = read_secret("DATABENTO_API_KEY");

    let command_dir = bundled_sidecar
        .as_ref()
        .map(|_| data_dir.clone())
        .unwrap_or_else(|| service_root.clone());
    let mut migration_command = if let Some(sidecar) = bundled_sidecar.as_ref() {
        let mut command = Command::new(sidecar);
        command.arg("migrate");
        command
    } else {
        let mut command = Command::new(&python);
        command.args(["-m", "worldstate.cli", "migrate"]);
        command
    };
    migration_command
        .current_dir(&command_dir)
        .env("WORLDSTATE_DATABASE_URL", &database_url);
    if bundled_sidecar.is_none() {
        migration_command
            .env("WORLDSTATE_ROOT", worldstate_root)
            .env("PYTHONPATH", &python_path);
    }
    let secret_environment = secret_environment(
        openai_secret.as_deref(),
        compatible_secret.as_deref(),
        fred_secret.as_deref(),
        bls_secret.as_deref(),
        trading_economics_secret.as_deref(),
        databento_secret.as_deref(),
    );
    for (name, secret) in &secret_environment {
        migration_command.env(name, secret);
    }
    let migration = migration_command
        .status()
        .map_err(|error| format!("Could not start database migration: {error}"))?;
    if !migration.success() {
        return Err(
            "WorldState database migration failed. Open the desktop log for details.".into(),
        );
    }

    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| error.to_string())?;
    let stderr = stdout.try_clone().map_err(|error| error.to_string())?;
    let mut api_command = if let Some(sidecar) = bundled_sidecar.as_ref() {
        let mut command = Command::new(sidecar);
        command.args(["serve", "--host", "127.0.0.1", "--port", "8000"]);
        command
    } else {
        let mut command = Command::new(&python);
        command.args([
            "-m",
            "worldstate.cli",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]);
        command
    };
    api_command
        .current_dir(&command_dir)
        .env("WORLDSTATE_DATABASE_URL", database_url)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));
    if bundled_sidecar.is_none() {
        api_command
            .env("WORLDSTATE_ROOT", worldstate_root)
            .env("PYTHONPATH", python_path);
    }
    for (name, secret) in &secret_environment {
        api_command.env(name, secret);
    }
    let child = api_command
        .spawn()
        .map_err(|error| format!("Could not start Research API: {error}"))?;

    *state
        .child
        .lock()
        .map_err(|_| "Backend state lock failed")? = Some(child);
    *state
        .database_path
        .lock()
        .map_err(|_| "Database state lock failed")? = Some(database_path);
    *state.log_path.lock().map_err(|_| "Log state lock failed")? = Some(log_path);
    *state
        .source
        .lock()
        .map_err(|_| "Backend state lock failed")? = "spawned".into();
    if bundled_sidecar.is_some() {
        *state
            .source
            .lock()
            .map_err(|_| "Backend state lock failed")? = "bundled-sidecar".into();
    }
    Ok(())
}

#[tauri::command]
async fn backend_status(
    state: tauri::State<'_, ResearchApiState>,
) -> Result<BackendStatus, String> {
    let health = fetch_health().await;
    let product_verified = health.as_ref().is_some_and(health_matches);
    let child_pid = state
        .child
        .lock()
        .ok()
        .and_then(|value| value.as_ref().map(Child::id));
    Ok(BackendStatus {
        reachable: product_verified,
        product_verified,
        api_url: API_URL,
        port: 8000,
        child_pid,
        ai_provider: health
            .and_then(|value| value.ai_provider)
            .unwrap_or_else(|| "unavailable".into()),
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
        source: state
            .source
            .lock()
            .map(|value| value.clone())
            .unwrap_or_else(|_| "unknown".into()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_identity_accepts_only_worldstate_v2() {
        let valid = HealthResponse {
            product: Some(EXPECTED_PRODUCT.into()),
            api_version: Some("v2".into()),
            ai_provider: Some("none".into()),
        };
        let foreign = HealthResponse {
            product: Some("another-service".into()),
            api_version: Some("v2".into()),
            ai_provider: None,
        };
        assert!(health_matches(&valid));
        assert!(!health_matches(&foreign));
    }

    #[test]
    fn compatible_secret_is_mapped_to_the_backend_environment() {
        let values = secret_environment(None, Some("secret-value"), None, None, None, None);
        assert_eq!(
            values,
            vec![("WORLDSTATE_AI_COMPATIBLE_API_KEY", "secret-value")]
        );
    }

    #[test]
    fn data_provider_secrets_are_mapped_without_values_in_status() {
        let values = secret_environment(
            None,
            None,
            Some("fred-secret"),
            Some("bls-secret"),
            Some("te-secret"),
            Some("databento-secret"),
        );
        assert_eq!(
            values.iter().map(|(name, _)| *name).collect::<Vec<_>>(),
            vec![
                "FRED_API_KEY",
                "BLS_API_KEY",
                "TRADING_ECONOMICS_API_KEY",
                "DATABENTO_API_KEY"
            ]
        );
    }

    #[test]
    fn occupied_foreign_port_is_rejected_instead_of_reused() {
        assert_eq!(existing_port_action(false, false).unwrap(), false);
        assert_eq!(existing_port_action(true, true).unwrap(), true);
        assert!(existing_port_action(true, false)
            .unwrap_err()
            .contains("not a verified WorldState"));
    }
}

#[tauri::command]
fn save_api_secret(name: String, value: String) -> Result<(), String> {
    if !ALLOWED_SECRET_NAMES.contains(&name.as_str()) {
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
            };
        }
    });
}
