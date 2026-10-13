use crate::connection::Connection;
use std::{
    fs,
    io::{Read, Write},
    path::Path,
};

#[cfg(windows)]
const SETTINGS_FILE: &str = "firm-connection.dpapi";
#[cfg(unix)]
const SETTINGS_FILE: &str = "firm-connection.json";
const MAX_PREFERENCE_BYTES: u64 = 65536;

fn inspect_directory(directory: &Path, create: bool) -> Result<bool, String> {
    if create {
        fs::create_dir_all(directory).map_err(|_| "Cannot create local connection settings.")?;
    }
    let metadata = match fs::symlink_metadata(directory) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(_) => return Err("Cannot inspect local connection settings.".into()),
    };
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err("Local connection settings must be an account-owned directory.".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        // Only URL preferences are stored here. Restrict access to this account.
        if metadata.uid() != unsafe { libc::geteuid() } {
            return Err("Local connection settings belong to another account.".into());
        }
        if create {
            fs::set_permissions(directory, fs::Permissions::from_mode(0o700))
                .map_err(|_| "Cannot restrict local connection settings to this account.")?;
        } else if metadata.mode() & 0o077 != 0 {
            return Err("Local connection settings are accessible to another account.".into());
        }
    }
    Ok(true)
}

fn inspect_file(metadata: &fs::Metadata) -> Result<(), String> {
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_PREFERENCE_BYTES
    {
        return Err("The saved server preference is invalid. Forget it and reconnect.".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o077 != 0 {
            return Err("The saved server preference is not private to this account.".into());
        }
    }
    Ok(())
}

pub fn save(directory: &Path, connection: &Connection) -> Result<(), String> {
    let validated = Connection::validate(&connection.server_url, connection.allow_loopback_http)?;
    let payload =
        serde_json::to_vec(&validated).map_err(|_| "Cannot encode the server preference.")?;
    let protected = protect(&payload)?;
    inspect_directory(directory, true)?;
    if let Ok(metadata) = fs::symlink_metadata(directory.join(SETTINGS_FILE)) {
        inspect_file(&metadata)?;
    }
    let mut temporary = tempfile::NamedTempFile::new_in(directory)
        .map_err(|_| "Cannot write local connection settings.")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        temporary
            .as_file()
            .set_permissions(fs::Permissions::from_mode(0o600))
            .map_err(|_| "Cannot restrict the server preference to this account.")?;
    }
    temporary
        .write_all(&protected)
        .and_then(|_| temporary.as_file().sync_all())
        .map_err(|_| "Cannot save the protected server preference.")?;
    temporary
        .persist(directory.join(SETTINGS_FILE))
        .map_err(|_| "Cannot replace the protected server preference.")?;
    Ok(())
}

pub fn load(directory: &Path) -> Result<Option<Connection>, String> {
    if !inspect_directory(directory, false)? {
        return Ok(None);
    }
    let path = directory.join(SETTINGS_FILE);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => {
            return Err(
                "Cannot read the saved server preference. You can forget it and reconnect.".into(),
            );
        }
    };
    inspect_file(&metadata)?;
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    let file = options
        .open(path)
        .map_err(|_| "Cannot read the saved server preference.")?;
    inspect_file(
        &file
            .metadata()
            .map_err(|_| "Cannot inspect the saved server preference.")?,
    )?;
    let mut data = Vec::new();
    file.take(MAX_PREFERENCE_BYTES + 1)
        .read_to_end(&mut data)
        .map_err(|_| "Cannot read the saved server preference.")?;
    if data.len() as u64 > MAX_PREFERENCE_BYTES {
        return Err("The saved server preference is too large. Forget it and reconnect.".into());
    }
    let payload = unprotect(&data)?;
    let saved: Connection = serde_json::from_slice(&payload)
        .map_err(|_| "The saved server preference is invalid. Forget it and reconnect.")?;
    Connection::validate(&saved.server_url, saved.allow_loopback_http).map(Some)
}

pub fn forget(directory: &Path) -> Result<(), String> {
    if !inspect_directory(directory, false)? {
        return Ok(());
    }
    match fs::remove_file(directory.join(SETTINGS_FILE)) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("Cannot remove the saved server preference.".into()),
    }
}

#[cfg(windows)]
fn transform(input: &[u8], encrypt: bool) -> Result<Vec<u8>, String> {
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{
            CRYPT_INTEGER_BLOB, CRYPTPROTECT_UI_FORBIDDEN, CryptProtectData, CryptUnprotectData,
        },
    };
    if input.is_empty() || input.len() > 65536 {
        return Err("The protected server preference is invalid. Forget it and reconnect.".into());
    }
    let source = CRYPT_INTEGER_BLOB {
        cbData: input.len() as u32,
        pbData: input.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    // DPAPI owns its output buffer. Copy it before returning it with LocalFree.
    unsafe {
        let result = if encrypt {
            CryptProtectData(
                &source,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null_mut(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } else {
            CryptUnprotectData(
                &source,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null_mut(),
                std::ptr::null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        };
        if result == 0 {
            return Err("Windows could not protect or read this server preference. Forget it and reconnect using this Windows account.".into());
        }
        let bytes = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        LocalFree(output.pbData.cast());
        Ok(bytes)
    }
}

#[cfg(windows)]
fn protect(input: &[u8]) -> Result<Vec<u8>, String> {
    transform(input, true)
}
#[cfg(windows)]
fn unprotect(input: &[u8]) -> Result<Vec<u8>, String> {
    transform(input, false)
}

#[cfg(unix)]
fn protect(input: &[u8]) -> Result<Vec<u8>, String> {
    Ok(input.to_vec())
}
#[cfg(unix)]
fn unprotect(input: &[u8]) -> Result<Vec<u8>, String> {
    Ok(input.to_vec())
}

#[cfg(all(test, unix))]
mod unix_tests {
    use super::*;
    use std::os::unix::fs::{PermissionsExt, symlink};

    #[test]
    fn preference_is_private_url_only_and_can_be_replaced_and_forgotten() {
        let directory = tempfile::tempdir().unwrap();
        let first = Connection::validate("https://cases.example.com", false).unwrap();
        save(directory.path(), &first).unwrap();
        let path = directory.path().join(SETTINGS_FILE);
        let payload: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(payload.as_object().unwrap().len(), 2);
        assert_eq!(payload["server_url"], first.server_url);
        assert_eq!(
            fs::metadata(directory.path()).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        assert_eq!(load(directory.path()).unwrap(), Some(first));
        let next = Connection::validate("https://second.example.com", false).unwrap();
        save(directory.path(), &next).unwrap();
        assert_eq!(load(directory.path()).unwrap(), Some(next));
        forget(directory.path()).unwrap();
        forget(directory.path()).unwrap();
        assert_eq!(load(directory.path()).unwrap(), None);
    }

    #[test]
    fn unsafe_permissions_and_corruption_fail_closed() {
        let directory = tempfile::tempdir().unwrap();
        let connection = Connection::validate("https://cases.example.com", false).unwrap();
        save(directory.path(), &connection).unwrap();
        let path = directory.path().join(SETTINGS_FILE);
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
        assert!(load(directory.path()).is_err());
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        fs::write(&path, b"invalid json").unwrap();
        assert!(load(directory.path()).is_err());
        fs::write(&path, vec![b'x'; 65537]).unwrap();
        assert!(load(directory.path()).is_err());
    }

    #[test]
    fn symlinked_preferences_and_directory_fail_closed_without_touching_target() {
        let root = tempfile::tempdir().unwrap();
        let settings = root.path().join("settings");
        let target = root.path().join("other.json");
        let connection = Connection::validate("https://cases.example.com", false).unwrap();
        save(&settings, &connection).unwrap();
        fs::write(&target, b"preserve this").unwrap();
        forget(&settings).unwrap();
        symlink(&target, settings.join(SETTINGS_FILE)).unwrap();
        assert!(load(&settings).is_err());
        assert!(save(&settings, &connection).is_err());
        forget(&settings).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"preserve this");
        let alias = root.path().join("alias");
        symlink(&settings, &alias).unwrap();
        assert!(save(&alias, &connection).is_err());
        assert!(load(&alias).is_err());
        assert!(forget(&alias).is_err());
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    #[test]
    fn preference_is_dpapi_protected_and_can_be_replaced_and_forgotten() {
        let directory = tempfile::tempdir().unwrap();
        let first = Connection::validate("https://cases.example.com", false).unwrap();
        save(directory.path(), &first).unwrap();
        let bytes = fs::read(directory.path().join(SETTINGS_FILE)).unwrap();
        assert!(!String::from_utf8_lossy(&bytes).contains("cases.example.com"));
        assert_eq!(load(directory.path()).unwrap(), Some(first));
        let next = Connection::validate("https://second.example.com", false).unwrap();
        save(directory.path(), &next).unwrap();
        assert_eq!(load(directory.path()).unwrap(), Some(next));
        forget(directory.path()).unwrap();
        forget(directory.path()).unwrap();
        assert_eq!(load(directory.path()).unwrap(), None);
    }
    #[test]
    fn corrupted_preference_fails_closed() {
        let directory = tempfile::tempdir().unwrap();
        fs::write(directory.path().join(SETTINGS_FILE), b"not encrypted").unwrap();
        assert!(load(directory.path()).is_err());
    }
}
