//! Commands the web layer calls through `invoke` (src/lib/tauri.ts). Each is a no-op in a browser.

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_autostart::ManagerExt as _;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_opener::OpenerExt;

/// The Windows accent color as `#rrggbb` (the UI follows it unless Settings overrides it).
#[tauri::command]
pub fn accent_color() -> Option<String> {
    accent_impl()
}

#[cfg(windows)]
fn accent_impl() -> Option<String> {
    use windows::UI::ViewManagement::{UIColorType, UISettings};
    let settings = UISettings::new().ok()?;
    let c = settings.GetColorValue(UIColorType::Accent).ok()?;
    Some(format!("#{:02x}{:02x}{:02x}", c.R, c.G, c.B))
}

#[cfg(not(windows))]
fn accent_impl() -> Option<String> {
    None
}

/// Pop Review or Edit out into its own window. Review opens in a portrait layout sized for the
/// 1080×1920 monitor; the window remembers its monitor and size (window-state plugin).
#[tauri::command]
pub async fn pop_out(app: AppHandle, kind: String, id: u32, path: String) -> Result<(), String> {
    if kind != "review" && kind != "edit" {
        return Err("unknown window kind".into());
    }
    if !path.starts_with("/popout/") {
        return Err("pop-out windows only open /popout routes".into());
    }
    let label = format!("{kind}-{id}");
    if let Some(w) = app.get_webview_window(&label) {
        let _ = w.show();
        let _ = w.set_focus();
        return Ok(());
    }
    let (w, h) = if kind == "review" { (1080.0, 1880.0) } else { (1440.0, 900.0) };
    let title = if kind == "review" { format!("Clipper — Review batch {id}") } else { format!("Clipper — Edit clip {id}") };
    WebviewWindowBuilder::new(&app, label, WebviewUrl::App(path.into()))
        .title(title)
        .inner_size(w, h)
        .min_inner_size(720.0, 760.0)
        .build()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

/// Windows toast ("12 clips ready for review", "TikTok account needs you").
#[tauri::command]
pub fn notify(app: AppHandle, title: String, body: String) -> Result<(), String> {
    app.notification().builder().title(title).body(body).show().map_err(|e| e.to_string())
}

/// External links open in the default browser, never inside the app.
#[tauri::command]
pub fn open_url(app: AppHandle, url: String) -> Result<(), String> {
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err("only http(s) links".into());
    }
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

/// Opens a folder in Explorer (data folder, logs). Only absolute paths.
#[tauri::command]
pub fn open_path(app: AppHandle, path: String) -> Result<(), String> {
    if !std::path::Path::new(&path).is_absolute() {
        return Err("absolute paths only".into());
    }
    app.opener().open_path(path, None::<&str>).map_err(|e| e.to_string())
}

/// Keeps the tray menu's checkmarks and today's stats in sync with the core.
#[tauri::command]
pub fn sync_tray(app: AppHandle, paused: bool, dry_run: bool, today: String) -> Result<(), String> {
    crate::tray::sync(&app, paused, dry_run, &today).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn autostart_get(app: AppHandle) -> Result<bool, String> {
    app.autolaunch().is_enabled().map_err(|e| e.to_string())
}

/// Start with Windows (Settings → General).
#[tauri::command]
pub fn autostart_set(app: AppHandle, enabled: bool) -> Result<(), String> {
    let launcher = app.autolaunch();
    if enabled { launcher.enable() } else { launcher.disable() }.map_err(|e| e.to_string())
}

/// Quit for real (the web layer confirms first when uploads are running).
#[tauri::command]
pub fn quit(app: AppHandle) {
    app.exit(0);
}
