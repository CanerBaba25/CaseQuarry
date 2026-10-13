//! Explicit packaged-runtime diagnostic; never reads real account preferences.
use crate::{
    connection::{Connection, trusted_settings_context},
    secure_store,
};
use std::{
    fs,
    io::Write,
    path::PathBuf,
    sync::atomic::{AtomicBool, Ordering},
};
use tauri::Manager;

pub struct RuntimeDiagnostic {
    pub directory: Option<tempfile::TempDir>,
    report: Option<PathBuf>,
    finished: AtomicBool,
}

impl RuntimeDiagnostic {
    pub fn from_arguments() -> Result<Self, String> {
        let enabled = std::env::args().any(|arg| arg == "--diagnose-runtime");
        let directory = if enabled {
            Some(
                tempfile::tempdir()
                    .map_err(|_| "Cannot create the runtime diagnostic directory.")?,
            )
        } else {
            None
        };
        let report = if enabled {
            let path = PathBuf::from(
                std::env::var_os("CASEQUARRY_DESKTOP_DIAGNOSTIC_REPORT").ok_or(
                    "Set CASEQUARRY_DESKTOP_DIAGNOSTIC_REPORT to a new absolute report path.",
                )?,
            );
            if !path.is_absolute()
                || path.exists()
                || !path.parent().is_some_and(|parent| parent.is_dir())
            {
                return Err(
                    "The runtime diagnostic report must be a new file in an existing directory."
                        .into(),
                );
            }
            Some(path)
        } else {
            None
        };
        Ok(Self {
            directory,
            report,
            finished: AtomicBool::new(false),
        })
    }

    fn preference_roundtrip(&self) -> Result<(), String> {
        let directory = self
            .directory
            .as_ref()
            .ok_or("Diagnostic is disabled.")?
            .path()
            .join("preferences");
        let connection = Connection::validate("https://example.invalid", false)?;
        secure_store::save(&directory, &connection)?;
        if secure_store::load(&directory)? != Some(connection) {
            return Err("Preference roundtrip failed.".into());
        }
        secure_store::forget(&directory)?;
        if secure_store::load(&directory)?.is_some() {
            return Err("Preference removal failed.".into());
        }
        Ok(())
    }

    pub fn finish(&self, app: &tauri::AppHandle, label: &str, url: &url::Url) {
        if self.directory.is_none() || self.finished.swap(true, Ordering::SeqCst) {
            return;
        }
        let context = trusted_settings_context(label, url);
        let preferences = self.preference_roundtrip().is_ok();
        let passed = context && preferences;
        let result = serde_json::json!({
            "version": env!("CARGO_PKG_VERSION"), "platform": std::env::consts::OS,
            "local_webview_loaded": context, "private_preference_roundtrip": preferences,
            "remote_server_probe": false, "passed": passed
        });
        let written = self.report.as_ref().is_some_and(|path| {
            fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)
                .and_then(|mut file| {
                    file.write_all(result.to_string().as_bytes())?;
                    file.sync_all()
                })
                .is_ok()
        });
        app.exit(if passed && written { 0 } else { 1 });
    }
}

pub fn settings_directory(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let diagnostic = app.state::<RuntimeDiagnostic>();
    if let Some(directory) = &diagnostic.directory {
        return Ok(directory.path().join("preferences"));
    }
    app.path()
        .app_config_dir()
        .map_err(|_| "Cannot locate local settings.".into())
}
