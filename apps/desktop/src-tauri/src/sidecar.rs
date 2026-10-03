//! The Python core (`clipper api`) runs as a sidecar: FastAPI on 127.0.0.1:8765, the agent
//! supervisor, workers and the Companion bridge. In development, run it yourself
//! (`just dev-api`) and the app connects to it.
//!
//! LOCAL-VERIFY: packaging the core as `binaries/clipper-core-<target-triple>.exe` (PyInstaller or
//! a uv-managed launcher) and that it exits with the app.

use std::sync::Mutex;
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

pub struct Core(pub Mutex<Option<CommandChild>>);

pub fn start(app: &AppHandle) {
    app.manage(Core(Mutex::new(None)));
    if cfg!(debug_assertions) && std::env::var("CLIPPER_SPAWN_CORE").is_err() {
        log::info!("dev build: not starting the core sidecar (run `just dev-api`)");
        return;
    }
    let cmd = match app.shell().sidecar("clipper-core") {
        Ok(c) => c.args(["api"]),
        Err(e) => {
            log::error!("core sidecar not bundled: {e}");
            return;
        }
    };
    match cmd.spawn() {
        Ok((mut rx, child)) => {
            *app.state::<Core>().0.lock().expect("core state poisoned") = Some(child);
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stderr(line) => {
                            log::info!("core: {}", String::from_utf8_lossy(&line))
                        }
                        CommandEvent::Terminated(status) => {
                            log::warn!("core exited: {:?}", status.code);
                            break;
                        }
                        _ => {}
                    }
                }
            });
        }
        Err(e) => log::error!("failed to start the core: {e}"),
    }
}

pub fn stop(app: &AppHandle) {
    if let Some(state) = app.try_state::<Core>() {
        if let Some(child) = state.0.lock().expect("core state poisoned").take() {
            let _ = child.kill();
        }
    }
}
