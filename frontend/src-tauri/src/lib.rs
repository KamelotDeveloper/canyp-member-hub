#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_log::Builder::default().level(log::LevelFilter::Info).build())
    .plugin(tauri_plugin_shell::init())
    .invoke_handler(tauri::generate_handler![save_export])
    .setup(|app| {
      #[cfg(all(desktop, not(debug_assertions)))]
      launch_backend_sidecar(app)?;

      #[cfg(debug_assertions)]
      let _ = app;

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}

/// Save an export file into the user's Downloads\canyp folder.
///
/// Returns the absolute path of the written file. `data` is base64-encoded
/// because bytes do not survive JSON IPC round-trips.
#[tauri::command]
fn save_export(filename: String, data: String) -> Result<String, String> {
  use base64::Engine;

  let bytes = base64::engine::general_purpose::STANDARD
    .decode(data.replace("\n", ""))
    .map_err(|e| format!("base64 decode error: {e}"))?;

  let profile = std::env::var("USERPROFILE").map_err(|_| "USERPROFILE not set".to_string())?;
  let dir = std::path::Path::new(&profile).join("Downloads").join("canyp");
  std::fs::create_dir_all(&dir).map_err(|e| format!("create dir error: {e}"))?;

  let path = dir.join(&filename);
  std::fs::write(&path, &bytes).map_err(|e| format!("write error: {e}"))?;
  Ok(path.to_string_lossy().to_string())
}

/// Start the FastAPI sidecar and register a killer for the app exit.
///
/// Only used in packaged (release) builds. In dev, the Vite proxy talks to a
/// manually-started uvicorn, so this must not spawn anything.
#[cfg(all(desktop, not(debug_assertions)))]
fn launch_backend_sidecar(
  app: &tauri::App,
) -> Result<(), Box<dyn std::error::Error>> {
  use tauri_plugin_shell::process::CommandEvent;
  use tauri_plugin_shell::ShellExt;
  use tauri::Manager;

  let sidecar_command = app.shell().sidecar("canyp-backend")?;
  let (mut rx, child) = sidecar_command.spawn()?;

  // Forward sidecar stdout/stderr to the Tauri logger.
  tauri::async_runtime::spawn(async move {
    while let Some(event) = rx.recv().await {
      match event {
        CommandEvent::Stdout(line) => {
          log::info!("[backend] {}", String::from_utf8_lossy(&line))
        }
        CommandEvent::Stderr(line) => {
          log::error!("[backend] {}", String::from_utf8_lossy(&line))
        }
        _ => {}
      }
    }
  });

  // Kill the sidecar when the last window closes (app teardown).
  app.manage(BackendProcess(std::sync::Mutex::new(Some(child))));
  Ok(())
}

/// Holds the spawned backend sidecar process so the app can kill it on exit.
#[cfg(all(desktop, not(debug_assertions)))]
struct BackendProcess(std::sync::Mutex<Option<tauri_plugin_shell::process::CommandChild>>);

#[cfg(all(desktop, not(debug_assertions)))]
impl Drop for BackendProcess {
  fn drop(&mut self) {
    if let Ok(mut guard) = self.0.lock() {
      if let Some(child) = guard.take() {
        let _ = child.kill();
      }
    }
  }
}