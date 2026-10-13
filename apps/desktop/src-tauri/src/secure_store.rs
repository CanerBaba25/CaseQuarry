use crate::connection::Connection;
use std::{fs, io::Write, path::Path};

const SETTINGS_FILE: &str = "firm-connection.dpapi";

pub fn save(directory: &Path, connection: &Connection) -> Result<(), String> {
    let validated = Connection::validate(&connection.server_url, connection.allow_loopback_http)?;
    let payload =
        serde_json::to_vec(&validated).map_err(|_| "Cannot encode the server preference.")?;
    let protected = protect(&payload)?;
    fs::create_dir_all(directory).map_err(|_| "Cannot create local connection settings.")?;
    let mut temporary = tempfile::NamedTempFile::new_in(directory)
        .map_err(|_| "Cannot write local connection settings.")?;
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
    let path = directory.join(SETTINGS_FILE);
    let metadata = match fs::metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => {
            return Err(
                "Cannot read the saved server preference. You can forget it and reconnect.".into(),
            );
        }
    };
    if metadata.len() > 65536 {
        return Err("The saved server preference is invalid. Forget it and reconnect.".into());
    }
    let data = fs::read(path).map_err(|_| "Cannot read the protected server preference.")?;
    let payload = unprotect(&data)?;
    let saved: Connection = serde_json::from_slice(&payload)
        .map_err(|_| "The saved server preference is invalid. Forget it and reconnect.")?;
    Connection::validate(&saved.server_url, saved.allow_loopback_http).map(Some)
}

pub fn forget(directory: &Path) -> Result<(), String> {
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

#[cfg(not(windows))]
fn protect(_: &[u8]) -> Result<Vec<u8>, String> {
    Err("Protected connection storage is currently supported on Windows only.".into())
}
#[cfg(not(windows))]
fn unprotect(_: &[u8]) -> Result<Vec<u8>, String> {
    Err("Protected connection storage is currently supported on Windows only.".into())
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
