#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod connection;
mod diagnostics;
mod secure_store;

use connection::{Connection, probe_server, trusted_settings_context};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

fn trusted_settings(window: &WebviewWindow) -> Result<(), String> {
    let url = window
        .url()
        .map_err(|_| "The local settings window is unavailable.")?;
    if trusted_settings_context(window.label(), &url) {
        Ok(())
    } else {
        Err("This action is available only in local connection settings.".into())
    }
}

fn show_settings(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("connection") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn get_connection(
    window: WebviewWindow,
    app: tauri::AppHandle,
) -> Result<Option<Connection>, String> {
    trusted_settings(&window)?;
    secure_store::load(&diagnostics::settings_directory(&app)?)
}

#[derive(serde::Serialize)]
struct Connected {
    server_url: String,
    setup_required: bool,
}

#[tauri::command]
async fn connect_server(
    window: WebviewWindow,
    app: tauri::AppHandle,
    server_url: String,
    allow_loopback_http: bool,
    remember: bool,
) -> Result<Connected, String> {
    trusted_settings(&window)?;
    if app
        .state::<diagnostics::RuntimeDiagnostic>()
        .directory
        .is_some()
    {
        return Err("Connecting to a firm is disabled during the runtime diagnostic.".into());
    }
    let connection = Connection::validate(&server_url, allow_loopback_http)?;
    let setup_required = probe_server(&connection).await?;
    let settings_dir = diagnostics::settings_directory(&app)?;
    if remember {
        secure_store::save(&settings_dir, &connection)?;
    } else {
        secure_store::forget(&settings_dir)?;
    }
    if let Some(existing) = app.get_webview_window("firm-workspace") {
        existing
            .destroy()
            .map_err(|_| "Cannot close the previous workspace.")?;
    }
    let remote_url = connection.url()?;
    let navigation_origin = remote_url.origin();
    let workspace = WebviewWindowBuilder::new(
        &app,
        "firm-workspace",
        WebviewUrl::External(remote_url),
    )
    .title("CaseQuarry — Firm workspace")
    .inner_size(1440.0, 940.0)
    .min_inner_size(700.0, 580.0)
    .incognito(true)
    .devtools(false)
    .disable_drag_drop_handler()
    .on_navigation(move |url| {
        url.origin() == navigation_origin && matches!(url.scheme(), "https" | "http")
    })
    .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
    .build()
    .map_err(
        |_| "The workspace window could not be opened. Check your system webview installation.",
    )?;
    let on_close_app = app.clone();
    workspace.on_window_event(move |event| {
        if matches!(event, tauri::WindowEvent::Destroyed) {
            show_settings(&on_close_app);
        }
    });
    window
        .hide()
        .map_err(|_| "Cannot hide the connection window.")?;
    Ok(Connected {
        server_url: connection.server_url,
        setup_required,
    })
}

#[tauri::command]
fn forget_connection(window: WebviewWindow, app: tauri::AppHandle) -> Result<(), String> {
    trusted_settings(&window)?;
    secure_store::forget(&diagnostics::settings_directory(&app)?)
}

fn main() {
    let diagnostic = diagnostics::RuntimeDiagnostic::from_arguments()
        .expect("CaseQuarry runtime diagnostic configuration is invalid");
    let diagnostic_enabled = diagnostic.directory.is_some();
    tauri::Builder::default()
        .manage(diagnostic)
        .on_page_load(|webview, payload| {
            if payload.event() == tauri::webview::PageLoadEvent::Finished {
                webview
                    .app_handle()
                    .state::<diagnostics::RuntimeDiagnostic>()
                    .finish(webview.app_handle(), webview.label(), payload.url());
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_connection,
            connect_server,
            forget_connection
        ])
        .setup(move |app| {
            if diagnostic_enabled {
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(30));
                    handle.exit(124);
                });
            }
            let settings = MenuItem::with_id(
                app,
                "settings",
                "Firm connection…",
                true,
                Some("CmdOrCtrl+Shift+C"),
            )?;
            let leave = MenuItem::with_id(app, "leave", "Close workspace", true, None::<&str>)?;
            let quit = PredefinedMenuItem::quit(app, Some("Exit CaseQuarry"))?;
            let menu = Menu::with_items(
                app,
                &[
                    &Submenu::with_items(app, "Connection", true, &[&settings, &leave, &quit])?,
                    &Submenu::with_items(
                        app,
                        "Edit",
                        true,
                        &[
                            &PredefinedMenuItem::undo(app, None)?,
                            &PredefinedMenuItem::redo(app, None)?,
                            &PredefinedMenuItem::separator(app)?,
                            &PredefinedMenuItem::cut(app, None)?,
                            &PredefinedMenuItem::copy(app, None)?,
                            &PredefinedMenuItem::paste(app, None)?,
                            &PredefinedMenuItem::select_all(app, None)?,
                        ],
                    )?,
                ],
            )?;
            app.set_menu(menu)?;
            if let Some(window) = app.get_webview_window("connection") {
                let handle = app.handle().clone();
                window.on_window_event(move |event| {
                    if matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                        handle.exit(0);
                    }
                });
            }
            Ok(())
        })
        .on_menu_event(|app, event| match event.id().as_ref() {
            "settings" => show_settings(app),
            "leave" => {
                if let Some(window) = app.get_webview_window("firm-workspace") {
                    let _ = window.close();
                }
                show_settings(app);
            }
            _ => {}
        })
        .run(tauri::generate_context!())
        .expect("CaseQuarry desktop could not start");
}
