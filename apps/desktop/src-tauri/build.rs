fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "get_connection",
            "connect_server",
            "forget_connection",
            "set_language",
        ]),
    ))
    .expect("desktop application manifest could not be built");
}
