//! Clipper desktop shell (Tauri v2): native Windows frame with Mica (tauri.conf.json), native menu
//! bar, tray, toasts, autostart, single instance, pop-out Review/Edit windows, and the Python core
//! as a sidecar. The React UI talks to the core over 127.0.0.1; Rust only does window/OS work.
//!
//! LOCAL-VERIFY: build and run on Windows 11 (`pnpm tauri dev`); this crate is only
//! `cargo check`ed on Linux in CI.

mod commands;
mod menu;
mod sidecar;
mod tray;

use tauri::{Emitter, Manager, WindowEvent};

pub const MAIN: &str = "main";

pub fn run() {
    tauri::Builder::default()
        // a second launch focuses the running window instead of starting another core
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main(app);
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            commands::accent_color,
            commands::pop_out,
            commands::notify,
            commands::open_url,
            commands::open_path,
            commands::sync_tray,
            commands::autostart_get,
            commands::autostart_set,
            commands::quit,
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            let main_menu = menu::build(&handle)?;
            app.set_menu(main_menu)?;
            app.on_menu_event(|app, event| {
                // every native menu item id is a command id the web layer knows (src/shell/commands.ts)
                let _ = app.emit_to(MAIN, "menu", event.id().0.as_str());
            });
            tray::build(&handle)?;
            sidecar::start(&handle);
            if std::env::args().any(|a| a == "--minimized") {
                if let Some(w) = app.get_webview_window(MAIN) {
                    let _ = w.hide();
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // closing the main window keeps the agents running in the tray (UI.md §2)
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == MAIN {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the Clipper app")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                sidecar::stop(app);
            }
        });
}

pub fn show_main(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window(MAIN) {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}
