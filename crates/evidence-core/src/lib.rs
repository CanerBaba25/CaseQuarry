//! Streaming source integrity and bounded MBOX preflight. No evidence mutation.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{self, BufRead, BufReader, Read};
use std::path::{Component, Path};

const BUFFER: usize = 64 * 1024;
pub const MAX_MANIFEST_BYTES: u64 = 64 * 1024 * 1024;
pub const MAX_MANIFEST_ITEMS: usize = 20_000;

#[derive(Debug, Serialize)]
pub struct FileHash {
    pub sha256: String,
    pub byte_size: u64,
    pub algorithm: &'static str,
}

pub fn hash_reader(mut source: impl Read) -> io::Result<FileHash> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; BUFFER];
    let mut bytes = 0_u64;
    loop {
        let amount = match source.read(&mut buffer) {
            Ok(amount) => amount,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        };
        if amount == 0 {
            break;
        }
        hasher.update(&buffer[..amount]);
        bytes = bytes
            .checked_add(amount as u64)
            .ok_or_else(|| io::Error::other("byte counter overflow"))?;
    }
    Ok(FileHash {
        sha256: format!("{:x}", hasher.finalize()),
        byte_size: bytes,
        algorithm: "sha256",
    })
}

pub fn hash_file(path: &Path) -> io::Result<FileHash> {
    if !fs::symlink_metadata(path)?.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "regular non-symlink file required",
        ));
    }
    hash_reader(File::open(path)?)
}

#[derive(Debug, Serialize)]
pub struct Verification {
    pub valid: bool,
    pub expected_sha256: String,
    pub actual_sha256: String,
    pub expected_bytes: Option<u64>,
    pub actual_bytes: u64,
}

pub fn verify_file(
    path: &Path,
    expected_sha256: &str,
    expected_bytes: Option<u64>,
) -> io::Result<Verification> {
    if expected_sha256.len() != 64 || !expected_sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "expected SHA-256 must have 64 hexadecimal digits",
        ));
    }
    let actual = hash_file(path)?;
    Ok(Verification {
        valid: actual.sha256.eq_ignore_ascii_case(expected_sha256)
            && expected_bytes.is_none_or(|size| size == actual.byte_size),
        expected_sha256: expected_sha256.to_lowercase(),
        actual_sha256: actual.sha256,
        expected_bytes,
        actual_bytes: actual.byte_size,
    })
}

fn bounded_line(
    source: &mut impl BufRead,
    target: &mut Vec<u8>,
    max_line_bytes: usize,
) -> io::Result<usize> {
    target.clear();
    loop {
        let available = match source.fill_buf() {
            Ok(available) => available,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        };
        if available.is_empty() {
            return Ok(target.len());
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let amount = newline.map_or(available.len(), |index| index + 1);
        if amount > max_line_bytes.saturating_sub(target.len()) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "MBOX line exceeds configured byte limit",
            ));
        }
        target.extend_from_slice(&available[..amount]);
        source.consume(amount);
        if newline.is_some() {
            return Ok(target.len());
        }
    }
}

#[derive(Debug, Serialize)]
pub struct MboxInventory {
    pub record_boundaries: u64,
    pub byte_size: u64,
    pub sha256: String,
    pub max_observed_message_bytes: u64,
    pub max_message_bytes: u64,
    pub max_line_bytes: usize,
    pub boundary_rule: &'static str,
}

pub fn scan_mbox_reader(
    source: impl Read,
    max_message_bytes: u64,
    max_line_bytes: usize,
) -> io::Result<MboxInventory> {
    if max_message_bytes == 0 || max_line_bytes == 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "positive scan limits required",
        ));
    }
    let mut source = BufReader::with_capacity(BUFFER, source);
    let mut line = Vec::with_capacity(BUFFER.min(max_line_bytes));
    let (mut records, mut bytes, mut current, mut peak) = (0_u64, 0_u64, 0_u64, 0_u64);
    let mut hasher = Sha256::new();
    while bounded_line(&mut source, &mut line, max_line_bytes)? > 0 {
        hasher.update(&line);
        bytes = bytes
            .checked_add(line.len() as u64)
            .ok_or_else(|| io::Error::other("byte counter overflow"))?;
        if line.starts_with(b"From ") {
            peak = peak.max(current);
            records = records
                .checked_add(1)
                .ok_or_else(|| io::Error::other("record counter overflow"))?;
            current = 0;
        }
        current = current
            .checked_add(line.len() as u64)
            .ok_or_else(|| io::Error::other("message counter overflow"))?;
        if current > max_message_bytes {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "MBOX message exceeds configured byte limit",
            ));
        }
    }
    peak = peak.max(current);
    Ok(MboxInventory {
        record_boundaries: records,
        byte_size: bytes,
        sha256: format!("{:x}", hasher.finalize()),
        max_observed_message_bytes: peak,
        max_message_bytes,
        max_line_bytes,
        boundary_rule: "mboxrd From-space line boundaries; MIME parsing remains in the ingestion worker",
    })
}

pub fn scan_mbox(
    path: &Path,
    max_message_bytes: u64,
    max_line_bytes: usize,
) -> io::Result<MboxInventory> {
    if !fs::symlink_metadata(path)?.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "regular non-symlink MBOX file required",
        ));
    }
    scan_mbox_reader(File::open(path)?, max_message_bytes, max_line_bytes)
}

#[derive(Debug, Deserialize)]
struct ManifestEntry {
    evidence_id: String,
    package_path: String,
    sha256: String,
    byte_size: u64,
}

#[derive(Debug, Deserialize)]
struct Manifest {
    schema_version: String,
    items: Vec<ManifestEntry>,
}

#[derive(Debug, Serialize)]
pub struct ManifestVerification {
    pub valid: bool,
    pub files_checked: usize,
    pub failed_evidence_ids: Vec<String>,
    pub algorithm: &'static str,
}

pub fn resolve_package_path(root: &Path, name: &str) -> io::Result<std::path::PathBuf> {
    let relative = Path::new(name);
    if name.contains(['\\', ':'])
        || name.is_empty()
        || relative
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "native manifest path must stay inside package root",
        ));
    }
    let root = root.canonicalize()?;
    let mut candidate = root.clone();
    for part in relative.components() {
        candidate.push(part.as_os_str());
        if fs::symlink_metadata(&candidate)?.file_type().is_symlink() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "native manifest path contains a symbolic link",
            ));
        }
    }
    let candidate = candidate.canonicalize()?;
    if !candidate.starts_with(root) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "native manifest path escapes package root",
        ));
    }
    Ok(candidate)
}

pub fn verify_manifest(path: &Path, root: &Path) -> io::Result<ManifestVerification> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.len() > MAX_MANIFEST_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "regular native manifest within 64 MiB is required",
        ));
    }
    let manifest: Manifest =
        serde_json::from_reader(File::open(path)?.take(MAX_MANIFEST_BYTES + 1)).map_err(|_| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid native hash manifest; metadata-only exports lack package_path",
            )
        })?;
    if manifest.schema_version != "casequarry-hash-manifest-v1"
        || manifest.items.len() > MAX_MANIFEST_ITEMS
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "unsupported manifest version or item limit",
        ));
    }
    let mut failed = Vec::new();
    for item in &manifest.items {
        let target = resolve_package_path(root, &item.package_path)?;
        if !verify_file(&target, &item.sha256, Some(item.byte_size))?.valid {
            failed.push(item.evidence_id.clone());
        }
    }
    Ok(ManifestVerification {
        valid: failed.is_empty(),
        files_checked: manifest.items.len(),
        failed_evidence_ids: failed,
        algorithm: "sha256",
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::sync::atomic::{AtomicU64, Ordering};
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    struct InterruptedReader<'a> {
        remaining: &'a [u8],
        interrupt: bool,
    }

    impl Read for InterruptedReader<'_> {
        fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
            if self.interrupt {
                self.interrupt = false;
                return Err(io::Error::from(io::ErrorKind::Interrupted));
            }
            self.interrupt = true;
            let amount = output.len().min(self.remaining.len()).min(7);
            output[..amount].copy_from_slice(&self.remaining[..amount]);
            self.remaining = &self.remaining[amount..];
            Ok(amount)
        }
    }

    #[test]
    fn streaming_hash_retries_interrupted_reads_without_losing_bytes() {
        let input = vec![0x83; BUFFER + 17];
        let actual = hash_reader(InterruptedReader {
            remaining: &input,
            interrupt: true,
        })
        .unwrap();
        let expected = hash_reader(Cursor::new(&input)).unwrap();
        assert_eq!(actual.sha256, expected.sha256);
        assert_eq!(actual.byte_size, expected.byte_size);
    }

    #[test]
    fn mbox_retries_interrupted_refills_without_changing_boundaries_or_size() {
        let input = b"From one\r\nSubject: first\r\n\r\n>From escaped\r\nFrom two\nSubject: last\n\nNo final newline";
        let actual = scan_mbox_reader(
            InterruptedReader {
                remaining: input,
                interrupt: true,
            },
            1024,
            512,
        )
        .unwrap();
        let expected = scan_mbox_reader(Cursor::new(input), 1024, 512).unwrap();
        assert_eq!(actual.record_boundaries, 2);
        assert_eq!(actual.record_boundaries, expected.record_boundaries);
        assert_eq!(actual.sha256, expected.sha256);
        assert_eq!(actual.byte_size, expected.byte_size);
        assert_eq!(
            actual.max_observed_message_bytes,
            expected.max_observed_message_bytes
        );
    }

    #[test]
    fn permanent_stream_errors_are_preserved() {
        struct FailedReader;
        impl Read for FailedReader {
            fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
                Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "read denied",
                ))
            }
        }
        for error in [
            hash_reader(FailedReader).unwrap_err(),
            scan_mbox_reader(FailedReader, 1024, 512).unwrap_err(),
        ] {
            assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
            assert_eq!(error.to_string(), "read denied");
        }
    }

    fn temp_file(contents: &[u8]) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "casequarry-native-{}-{}.bin",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::SeqCst)
        ));
        let mut file = File::create_new(&path).unwrap();
        std::io::Write::write_all(&mut file, contents).unwrap();
        path
    }

    #[test]
    fn known_sha256_and_wrong_size_fail() {
        let path = temp_file(b"abc");
        let expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        assert!(verify_file(&path, expected, Some(3)).unwrap().valid);
        assert!(!verify_file(&path, expected, Some(4)).unwrap().valid);
        assert!(!verify_file(&path, &"0".repeat(64), None).unwrap().valid);
        assert_eq!(fs::read(&path).unwrap(), b"abc");
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn mbox_escape_and_eof_are_streamed() {
        let input = b"From one Thu Jan 01 00:00:00 2025\nSubject: First\n\n>From escaped body\n\nFrom two Thu Jan 01 00:00:00 2025\nSubject: Second\n\nNo trailing newline";
        let report = scan_mbox_reader(Cursor::new(input), 1024, 512).unwrap();
        assert_eq!(report.record_boundaries, 2);
        assert_eq!(report.byte_size, input.len() as u64);
        assert_eq!(
            report.sha256,
            hash_reader(Cursor::new(input)).unwrap().sha256
        );
    }

    #[test]
    fn mbox_limits_refuse_unbounded_lines_and_messages() {
        assert!(scan_mbox_reader(Cursor::new(vec![b'x'; 1025]), 2048, 1024).is_err());
        assert!(scan_mbox_reader(Cursor::new(b"From one\nshort\nshort\n"), 10, 1024).is_err());
    }

    #[test]
    fn malicious_manifest_paths_are_refused_before_open() {
        for name in [
            "../secret",
            "/absolute",
            "native/../../secret",
            "C:/secret",
            "native\\secret",
            "",
        ] {
            assert!(resolve_package_path(&std::env::temp_dir(), name).is_err());
        }
    }

    #[test]
    fn native_manifest_verifies_and_detects_changed_original() {
        let original = temp_file(b"Synthetic original");
        let root = original.parent().unwrap();
        let name = original.file_name().unwrap().to_str().unwrap();
        let hashed = hash_file(&original).unwrap();
        let manifest = temp_file(serde_json::json!({"schema_version": "casequarry-hash-manifest-v1", "items": [{"evidence_id": "SYN-1", "package_path": name, "sha256": hashed.sha256, "byte_size": hashed.byte_size}]}).to_string().as_bytes());
        assert!(verify_manifest(&manifest, root).unwrap().valid);
        fs::write(&original, b"Tampered synthetic bytes").unwrap();
        assert!(!verify_manifest(&manifest, root).unwrap().valid);
        fs::remove_file(original).unwrap();
        fs::remove_file(manifest).unwrap();
    }
}
