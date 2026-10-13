use casequarry_evidence_core::{hash_file, scan_mbox, verify_file, verify_manifest};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::io;
use std::path::Path;

fn execute(args: &[String]) -> io::Result<Value> {
    let command = args.first().map(String::as_str).unwrap_or("--help");
    let path = || {
        args.get(1)
            .map(Path::new)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "file argument required"))
    };
    let allowed: &[&str] = match command {
        "verify" => &["--sha256", "--bytes"],
        "scan-mbox" => &["--max-message-bytes", "--max-line-bytes"],
        "manifest" => &["--root"],
        _ => &[],
    };
    let mut options = BTreeMap::new();
    for pair in args.get(2..).unwrap_or_default().chunks(2) {
        let name = pair[0].as_str();
        if !allowed.contains(&name) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("unsupported option {name} for {command}"),
            ));
        }
        let value = pair
            .get(1)
            .filter(|value| !value.starts_with("--"))
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("{name} requires a value"),
                )
            })?;
        if options.insert(name, value.as_str()).is_some() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("duplicate option {name}"),
            ));
        }
    }
    let option = |name: &str| options.get(name).copied();
    match command {
        "hash" => Ok(json!(hash_file(path()?)?)),
        "verify" => {
            let expected = option("--sha256").ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "--sha256 is required")
            })?;
            let size = option("--bytes")
                .map(str::parse::<u64>)
                .transpose()
                .map_err(|_| {
                    io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "--bytes must be an unsigned integer",
                    )
                })?;
            Ok(json!(verify_file(path()?, expected, size)?))
        }
        "scan-mbox" => {
            let message_limit = option("--max-message-bytes")
                .unwrap_or("268435456")
                .parse::<u64>()
                .map_err(|_| {
                    io::Error::new(io::ErrorKind::InvalidInput, "invalid message byte limit")
                })?;
            let line_limit = option("--max-line-bytes")
                .unwrap_or("8388608")
                .parse::<usize>()
                .map_err(|_| {
                    io::Error::new(io::ErrorKind::InvalidInput, "invalid line byte limit")
                })?;
            Ok(json!(scan_mbox(path()?, message_limit, line_limit)?))
        }
        "manifest" => {
            let root = option("--root")
                .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "--root is required"))?;
            Ok(json!(verify_manifest(path()?, Path::new(root))?))
        }
        _ => Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "supported commands: hash FILE; verify FILE --sha256 HASH [--bytes N]; scan-mbox FILE; manifest FILE --root DIRECTORY",
        )),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().is_some_and(|value| value == "--version") {
        println!("casequarry-evidence {}", env!("CARGO_PKG_VERSION"));
        return;
    }
    if args.is_empty() || args.first().is_some_and(|value| value == "--help") {
        println!(
            "casequarry-evidence: hash FILE | verify FILE --sha256 HASH [--bytes N] | scan-mbox FILE | manifest FILE --root DIRECTORY"
        );
        return;
    }
    match execute(&args) {
        Ok(value) => {
            println!("{value}");
            if value.get("valid").and_then(Value::as_bool) == Some(false) {
                std::process::exit(8);
            }
        }
        Err(error) => {
            let code = match error.kind() {
                io::ErrorKind::NotFound => 4,
                io::ErrorKind::PermissionDenied => 3,
                io::ErrorKind::InvalidInput | io::ErrorKind::InvalidData => 2,
                _ => 7,
            };
            eprintln!(
                "{}",
                json!({"error_code": "NATIVE_VERIFICATION_ERROR", "message": error.to_string()})
            );
            std::process::exit(code);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
    };
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn fixture() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "casequarry-native-args-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::SeqCst)
        ));
        let mut file = fs::File::create_new(&path).unwrap();
        std::io::Write::write_all(&mut file, b"abc").unwrap();
        path
    }

    #[test]
    fn supplied_size_limit_requires_a_value() {
        let path = fixture();
        let args = [
            "verify",
            path.to_str().unwrap(),
            "--sha256",
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            "--bytes",
        ]
        .map(str::to_string);
        let result = execute(&args);
        fs::remove_file(path).unwrap();
        assert_eq!(result.unwrap_err().kind(), io::ErrorKind::InvalidInput);
    }

    #[test]
    fn supplied_mbox_limits_require_values() {
        let path = fixture();
        for option in ["--max-message-bytes", "--max-line-bytes"] {
            let args = ["scan-mbox", path.to_str().unwrap(), option].map(str::to_string);
            assert_eq!(
                execute(&args).unwrap_err().kind(),
                io::ErrorKind::InvalidInput
            );
        }
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn options_are_explicit_and_valid_size_checks_are_preserved() {
        let path = fixture();
        let sha256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        for suffix in [
            vec!["--sha256", sha256, "--bytes", "--root"],
            vec!["--sha256", sha256, "--bytes", "3", "--bytes", "4"],
            vec!["--sha256", sha256, "--byte", "4"],
        ] {
            let mut args = vec!["verify".to_string(), path.to_str().unwrap().to_string()];
            args.extend(suffix.into_iter().map(str::to_string));
            assert_eq!(
                execute(&args).unwrap_err().kind(),
                io::ErrorKind::InvalidInput
            );
        }
        for (bytes, valid) in [("3", true), ("4", false)] {
            let args = [
                "verify",
                path.to_str().unwrap(),
                "--sha256",
                sha256,
                "--bytes",
                bytes,
            ]
            .map(str::to_string);
            let result = execute(&args).unwrap();
            assert_eq!(result["valid"], valid);
            assert_eq!(result["expected_bytes"], bytes.parse::<u64>().unwrap());
        }
        assert_eq!(fs::read(&path).unwrap(), b"abc");
        fs::remove_file(path).unwrap();
    }
}
