use casequarry_evidence_core::{hash_file, scan_mbox, verify_file, verify_manifest};
use serde_json::{Value, json};
use std::io;
use std::path::Path;

fn execute(args: &[String]) -> io::Result<Value> {
    let command = args.first().map(String::as_str).unwrap_or("--help");
    let path = || {
        args.get(1)
            .map(Path::new)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "file argument required"))
    };
    let option = |name: &str| {
        args.windows(2)
            .find(|pair| pair[0] == name)
            .map(|pair| pair[1].as_str())
    };
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
