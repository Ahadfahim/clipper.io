//! Native Windows menu bar. Item ids match the web command registry (src/shell/commands.ts), so a
//! click is forwarded as a `menu` event and runs the same command as Ctrl+K or the shortcut.

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Wry};

fn item(
    app: &AppHandle,
    id: &str,
    text: &str,
    accel: Option<&str>,
) -> tauri::Result<MenuItem<Wry>> {
    MenuItem::with_id(app, id, text, true, accel)
}

pub fn build(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let sep = || PredefinedMenuItem::separator(app);
    let file = Submenu::with_items(
        app,
        "&File",
        true,
        &[
            &item(app, "go.settings", "&Settings…", Some("Ctrl+,"))?,
            &item(app, "file.setup", "Run setup &wizard…", None)?,
            &item(app, "file.data", "Open &data folder", None)?,
            &sep()?,
            &item(app, "app.quit", "E&xit", None)?,
        ],
    )?;
    let edit = Submenu::with_items(
        app,
        "&Edit",
        true,
        &[
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
            &sep()?,
            &item(app, "edit.find", "&Find…", Some("Ctrl+K"))?,
        ],
    )?;
    let view = Submenu::with_items(
        app,
        "&View",
        true,
        &[
            &item(app, "go.overview", "&Overview", Some("Ctrl+1"))?,
            &item(app, "go.agents", "&Agents", Some("Ctrl+2"))?,
            &item(app, "go.campaigns", "&Campaigns", Some("Ctrl+3"))?,
            &item(app, "go.library", "&Library", Some("Ctrl+4"))?,
            &item(app, "go.review", "&Review", Some("Ctrl+5"))?,
            &item(app, "go.publishing", "&Publishing", Some("Ctrl+6"))?,
            &item(app, "go.earnings", "&Earnings", Some("Ctrl+7"))?,
            &sep()?,
            &item(app, "view.output", "Output &panel", Some("Ctrl+J"))?,
            &item(app, "review.popout", "Pop out Review &window", None)?,
            &sep()?,
            &item(app, "view.theme.system", "Theme: follow Windows", None)?,
            &item(app, "view.theme.light", "Theme: light", None)?,
            &item(app, "view.theme.dark", "Theme: dark", None)?,
        ],
    )?;
    let agents = Submenu::with_items(
        app,
        "&Agents",
        true,
        &[
            &item(
                app,
                "agents.pause",
                "&Pause all / Resume",
                Some("Ctrl+Shift+P"),
            )?,
            &CheckMenuItem::with_id(
                app,
                "agents.dryrun",
                "&Dry run",
                true,
                true,
                Some("Ctrl+Shift+D"),
            )?,
            &item(app, "agents.director", "Message the &Director…", None)?,
            &sep()?,
            &Submenu::with_items(
                app,
                "Slot &count",
                true,
                &[
                    &item(app, "agents.slots.1", "1", None)?,
                    &item(app, "agents.slots.2", "2", None)?,
                    &item(app, "agents.slots.3", "3", None)?,
                    &item(app, "agents.slots.4", "4", None)?,
                    &item(app, "agents.slots.6", "6", None)?,
                    &item(app, "agents.slots.8", "8", None)?,
                    &item(app, "agents.slots.0", "&Unlimited (grows with the campaigns)", None)?,
                    &sep()?,
                    &item(app, "agents.slots.default", "Use the Settings value", None)?,
                ],
            )?,
            &sep()?,
            &item(app, "agents.stop", "&Stop all…", None)?,
        ],
    )?;
    let campaigns = Submenu::with_items(
        app,
        "&Campaigns",
        true,
        &[
            &item(app, "campaigns.scout", "&Scout now", None)?,
            &item(app, "campaigns.paste", "&Paste campaign URL…", None)?,
            &item(app, "review.open", "&Review queue", None)?,
        ],
    )?;
    let tools = Submenu::with_items(
        app,
        "&Tools",
        true,
        &[
            &item(app, "tools.doctor", "Clipper &doctor", None)?,
            &item(app, "tools.analyst", "Run &analyst now", None)?,
            &item(app, "tools.memory", "&Memory…", None)?,
        ],
    )?;
    let help = Submenu::with_items(
        app,
        "&Help",
        true,
        &[
            &item(app, "help.keys", "&Keyboard shortcuts", Some("F1"))?,
            &item(app, "file.gallery", "Component &gallery", None)?,
        ],
    )?;
    Menu::with_items(
        app,
        &[&file, &edit, &view, &agents, &campaigns, &tools, &help],
    )
}
