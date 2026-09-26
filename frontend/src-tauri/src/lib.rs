use std::net::TcpListener;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_log::Builder::default().level(log::LevelFilter::Info).build())
    .plugin(tauri_plugin_shell::init())
    .invoke_handler(tauri::generate_handler![
      save_export,
      get_backend_port,
      whatsapp_desktop_available
    ])
    .setup(|app| {
      #[cfg(all(desktop, not(debug_assertions)))]
      launch_backend_sidecar(app)?;

      // Dev sin sidecar: el comando get_backend_port devuelve el fallback.
      #[cfg(debug_assertions)]
      app.manage(BackendPort(8000));

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}

/// Puerto del sidecar elegido en el setup (dinámico por arranque).
#[derive(Clone, Copy)]
struct BackendPort(u16);

/// Devuelve el puerto del backend local. En dev (sin sidecar) cae a 8000.
#[tauri::command]
fn get_backend_port(state: tauri::State<'_, BackendPort>) -> u16 {
  state.0
}

/// Detect whether a native WhatsApp handler exists before opening `whatsapp://`.
///
/// On Windows, `tauri-plugin-shell` `open()` shells out to `cmd start`, which
/// shows the native "no app associated" dialog WITHOUT rejecting the promise, so
/// the JS fallback never runs. Querying the registry association up front lets
/// the frontend fall back to WhatsApp Web cleanly.
#[tauri::command]
fn whatsapp_desktop_available() -> bool {
  #[cfg(target_os = "windows")]
  {
    use std::process::Command;
    Command::new("reg")
      .args(["query", r"HKEY_CLASSES_ROOT\whatsapp"])
      .stdin(std::process::Stdio::null())
      .stdout(std::process::Stdio::null())
      .stderr(std::process::Stdio::null())
      .output()
      .map(|o| o.status.success())
      .unwrap_or(false)
  }
  #[cfg(not(target_os = "windows"))]
  {
    true
  }
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

  let mut sidecar_command = app
    .shell()
    .sidecar("canyp-backend")?
    // Packaged client builds must never run in local data mode: the backend
    // refuses to fall back to SQLite when this flag is set.
    .env("CANYP_CLIENT_BUILD", "1");
  // The Supabase URL is baked at compile time (env var set in the shell that
  // runs `tauri build`) and passed straight to the backend, which honors
  // DATABASE_URL over any persisted settings. It is never read from settings.
  if let Some(url) = option_env!("CANYP_DATABASE_URL") {
    if !url.is_empty() {
      sidecar_command = sidecar_command.env("DATABASE_URL", url);
    }
  }
  // Puerto dinámico: el SO asigna un puerto libre, se pasa al sidecar y se
  // expone al frontend. CANYP nunca depende de un puerto fijo (evita choques
  // con Ordo-ERP u otro software en la máquina del cliente).
  let probe = TcpListener::bind("127.0.0.1:0")?;
  let port = probe.local_addr()?.port();
  drop(probe);
  sidecar_command = sidecar_command.env("CANYP_PORT", port.to_string());
  app.manage(BackendPort(port));
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