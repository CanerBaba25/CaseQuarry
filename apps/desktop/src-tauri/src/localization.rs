use serde::Deserialize;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MenuLabels {
    pub connection: String,
    pub firm_connection: String,
    pub close_workspace: String,
    pub exit_case_quarry: String,
    pub edit: String,
    pub undo: String,
    pub redo: String,
    pub cut: String,
    pub copy: String,
    pub paste: String,
    pub select_all: String,
}

impl Default for MenuLabels {
    fn default() -> Self {
        Self {
            connection: "Connection".into(),
            firm_connection: "Firm connection…".into(),
            close_workspace: "Close workspace".into(),
            exit_case_quarry: "Exit CaseQuarry".into(),
            edit: "Edit".into(),
            undo: "Undo".into(),
            redo: "Redo".into(),
            cut: "Cut".into(),
            copy: "Copy".into(),
            paste: "Paste".into(),
            select_all: "Select all".into(),
        }
    }
}

pub fn validate(language: &str, labels: &MenuLabels) -> Result<(), String> {
    if ![
        "en", "ru", "fr", "es", "de", "tr", "el", "it", "pt", "uk", "zh-Hans", "zh-Hant", "hi",
    ]
    .contains(&language)
    {
        return Err("Choose a supported interface language.".into());
    }
    for value in [
        &labels.connection,
        &labels.firm_connection,
        &labels.close_workspace,
        &labels.exit_case_quarry,
        &labels.edit,
        &labels.undo,
        &labels.redo,
        &labels.cut,
        &labels.copy,
        &labels.paste,
        &labels.select_all,
    ] {
        if value.trim().is_empty()
            || value.chars().count() > 200
            || value.chars().any(char::is_control)
        {
            return Err("Choose a supported interface language.".into());
        }
    }
    Ok(())
}

pub fn menu(app: &tauri::AppHandle, labels: &MenuLabels) -> tauri::Result<Menu<tauri::Wry>> {
    let settings = MenuItem::with_id(
        app,
        "settings",
        &labels.firm_connection,
        true,
        Some("CmdOrCtrl+Shift+C"),
    )?;
    let leave = MenuItem::with_id(app, "leave", &labels.close_workspace, true, None::<&str>)?;
    let quit = PredefinedMenuItem::quit(app, Some(&labels.exit_case_quarry))?;
    Menu::with_items(
        app,
        &[
            &Submenu::with_items(app, &labels.connection, true, &[&settings, &leave, &quit])?,
            &Submenu::with_items(
                app,
                &labels.edit,
                true,
                &[
                    &PredefinedMenuItem::undo(app, Some(&labels.undo))?,
                    &PredefinedMenuItem::redo(app, Some(&labels.redo))?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::cut(app, Some(&labels.cut))?,
                    &PredefinedMenuItem::copy(app, Some(&labels.copy))?,
                    &PredefinedMenuItem::paste(app, Some(&labels.paste))?,
                    &PredefinedMenuItem::select_all(app, Some(&labels.select_all))?,
                ],
            )?,
        ],
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supported_native_languages_accept_bounded_unicode_labels() {
        for language in [
            "en", "ru", "fr", "es", "de", "tr", "el", "it", "pt", "uk", "zh-Hans", "zh-Hant", "hi",
        ] {
            let labels = MenuLabels {
                connection: "连接 · भाषा · Σύνδεση".into(),
                ..MenuLabels::default()
            };
            assert!(validate(language, &labels).is_ok());
        }
    }

    #[test]
    fn native_language_rejects_unknown_codes_and_unsafe_menu_text() {
        assert!(validate("unsupported", &MenuLabels::default()).is_err());
        for value in [
            "".to_string(),
            " ".into(),
            "x".repeat(201),
            "unsafe\nmenu".into(),
        ] {
            let labels = MenuLabels {
                connection: value,
                ..MenuLabels::default()
            };
            assert!(validate("en", &labels).is_err());
        }
    }
}
