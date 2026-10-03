//! Tray icon: Open · Pause all / Resume · Dry run · today's stats · Quit (UI.md §2). Closing the
//! window only hides it; agents keep running until Quit.

use std::sync::Mutex;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Wry};

pub struct TrayItems {
    pause: MenuItem<Wry>,
    dry_run: CheckMenuItem<Wry>,
    today: MenuItem<Wry>,
}

pub struct TrayState(pub Mutex<Option<TrayItems>>);

pub fn build(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "tray.open", "Open Clipper", true, None::<&str>)?;
    let pause = MenuItem::with_id(app, "agents.pause", "Pause all", true, None::<&str>)?;
    let dry_run =
        CheckMenuItem::with_id(app, "agents.dryrun", "Dry run", true, true, None::<&str>)?;
    let today = MenuItem::with_id(app, "tray.today", "Today: —", false, None::<&str>)?;
    let quit = MenuItem::with_id(app, "app.quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &open,
            &PredefinedMenuItem::separator(app)?,
            &pause,
            &dry_run,
            &today,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;
    let mut builder = TrayIconBuilder::with_id("clipper")
        .tooltip("Clipper")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().0.as_str() {
            "tray.open" => crate::show_main(app),
            // Quit, Pause and Dry run go through the web layer: it confirms Quit while uploads run
            // and calls the core API for the switches.
            id => {
                crate::show_main(app);
                let _ = app.emit_to(crate::MAIN, "menu", id);
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                crate::show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    app.manage(TrayState(Mutex::new(Some(TrayItems {
        pause,
        dry_run,
        today,
    }))));
    Ok(())
}

pub fn sync(app: &AppHandle, paused: bool, dry_run: bool, today: &str) -> tauri::Result<()> {
    let state = app.state::<TrayState>();
    let guard = state.0.lock().expect("tray state poisoned");
    if let Some(items) = guard.as_ref() {
        items
            .pause
            .set_text(if paused { "Resume" } else { "Pause all" })?;
        items.dry_run.set_checked(dry_run)?;
        items.today.set_text(format!("Today: {today}"))?;
    }
    if let Some(tray) = app.tray_by_id("clipper") {
        let tip = format!(
            "Clipper · {}{} · {today}",
            if paused { "paused" } else { "running" },
            if dry_run { " · dry run" } else { "" }
        );
        tray.set_tooltip(Some(tip))?;
    }
    Ok(())
}
