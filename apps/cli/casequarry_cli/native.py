"""Optional native integrity helpers, with fixed binary paths and bounded fallback."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .client import fail

ROOT = Path(__file__).resolve().parents[3]
COMMANDS = {"hash", "verify", "manifest", "scan-mbox"}


def binary_path() -> Path:
    return (
        ROOT
        / "target"
        / "release"
        / ("casequarry-evidence.exe" if os.name == "nt" else "casequarry-evidence")
    )


def native_available() -> bool:
    path = binary_path()
    return (
        path.is_file()
        and not path.is_symlink()
        and path.resolve().is_relative_to(ROOT.resolve() / "target" / "release")
    )


def run_native(command: str, arguments: list[str]) -> dict[str, Any]:
    if command not in COMMANDS:
        fail("Unsupported native operation.", 2)
    if not native_available():
        fail("Native verifier is not built. Run cargo build --release --locked or choose --engine python.", 7)
    try:
        result = subprocess.run(
            [str(binary_path()), command, *arguments],
            shell=False,
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("Native verification could not complete; check the built binary and input limits.", 7)
    try:
        output = result.stdout if result.stdout.strip() else result.stderr
        payload = json.loads(output.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected a structured result")
    except ValueError:
        fail("Native verifier returned an invalid structured result.", 7)
    if result.returncode not in {0, 8}:
        fail(
            payload.get("message", "Native verification failed."),
            result.returncode if result.returncode in {2, 3, 4, 7} else 7,
        )
    return {**payload, "engine": "rust"}


def use_native(engine: str) -> bool:
    if engine not in {"auto", "rust", "python"}:
        fail("--engine must be auto, rust or python.", 2)
    return engine == "rust" or engine == "auto" and native_available()


def hash_file(path: Path, engine: str = "auto") -> dict:
    if use_native(engine):
        return run_native("hash", [str(path)])
    if path.is_symlink() or not path.is_file():
        fail("A regular non-symlink source file is required.", 4)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "byte_size": size, "algorithm": "sha256", "engine": "python"}


def verify_file(path: Path, expected: str, byte_size: int | None, engine: str = "auto") -> dict:
    if len(expected) != 64 or any(char not in "0123456789abcdefABCDEF" for char in expected):
        fail("--sha256 requires 64 hexadecimal digits.", 2)
    if use_native(engine):
        arguments = [str(path), "--sha256", expected]
        if byte_size is not None:
            arguments += ["--bytes", str(byte_size)]
        return run_native("verify", arguments)
    value = hash_file(path, "python")
    return {
        "valid": value["sha256"] == expected.lower()
        and (byte_size is None or value["byte_size"] == byte_size),
        "expected_sha256": expected.lower(),
        "actual_sha256": value["sha256"],
        "expected_bytes": byte_size,
        "actual_bytes": value["byte_size"],
        "engine": "python",
    }


def scan_mbox(
    path: Path,
    engine: str = "auto",
    max_message_bytes: int = 256 * 1024 * 1024,
    max_line_bytes: int = 8 * 1024 * 1024,
) -> dict:
    if use_native(engine):
        return run_native(
            "scan-mbox",
            [
                str(path),
                "--max-message-bytes",
                str(max_message_bytes),
                "--max-line-bytes",
                str(max_line_bytes),
            ],
        )
    if path.is_symlink() or not path.is_file() or max_line_bytes <= 0 or max_message_bytes <= 0:
        fail("A regular MBOX file and positive scan limits are required.", 2)
    digest = hashlib.sha256()
    records, size, current, peak = 0, 0, 0, 0
    with path.open("rb") as source:
        while line := source.readline(max_line_bytes + 1):
            if len(line) > max_line_bytes:
                fail("MBOX line exceeds the configured byte limit.", 2)
            digest.update(line)
            size += len(line)
            if line.startswith(b"From "):
                records += 1
                peak = max(peak, current)
                current = 0
            current += len(line)
            if current > max_message_bytes:
                fail("MBOX message exceeds the configured byte limit.", 2)
    return {
        "record_boundaries": records,
        "byte_size": size,
        "sha256": digest.hexdigest(),
        "max_observed_message_bytes": max(peak, current),
        "max_message_bytes": max_message_bytes,
        "max_line_bytes": max_line_bytes,
        "boundary_rule": "mboxrd From-space line boundaries; MIME parsing remains in the ingestion worker",
        "engine": "python",
    }


def package_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "\\" in value or ":" in value or not value:
        fail("Manifest path must remain inside the native package root.", 2)
    root = root.resolve()
    target = root
    for part in relative.parts:
        target = target / part
        if target.is_symlink():
            fail("Native manifest paths cannot contain symbolic links.", 2)
    if not target.resolve().is_relative_to(root):
        fail("Manifest path escapes the native package root.", 2)
    return target


def verify_manifest(path: Path, root: Path, engine: str = "auto") -> dict:
    if use_native(engine):
        return run_native("manifest", [str(path), "--root", str(root)])
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        fail("A regular native hash manifest within 64 MiB is required.", 2)
    try:
        with path.open("rb") as source:
            data = json.loads(source.read(64 * 1024 * 1024 + 1))
        items = data["items"]
        if data["schema_version"] != "casequarry-hash-manifest-v1" or not isinstance(items, list) or len(items) > 20_000:
            fail("Unsupported manifest version or item limit.", 2)
        failed = []
        for item in items:
            if (
                not isinstance(item, dict)
                or any(not isinstance(item.get(field), str) for field in ("evidence_id", "package_path", "sha256"))
                or type(item.get("byte_size")) is not int
                or not 0 <= item["byte_size"] <= 2**64 - 1
            ):
                raise ValueError("Invalid native manifest item")
            target = package_path(root, item["package_path"])
            if not verify_file(target, item["sha256"], item["byte_size"], "python")["valid"]:
                failed.append(item["evidence_id"])
        return {
            "valid": not failed,
            "files_checked": len(items),
            "failed_evidence_ids": failed,
            "algorithm": "sha256",
            "engine": "python",
        }
    except (OSError, ValueError, KeyError, TypeError):
        fail("Invalid native hash manifest; metadata-only exports do not contain native package paths.", 2)
