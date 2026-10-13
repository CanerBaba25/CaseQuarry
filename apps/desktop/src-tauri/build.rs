fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "get_connection",
            "connect_server",
            "forget_connection",
        ]),
    ))
    .expect("desktop application manifest could not be built");
}
