"""Validate packaged application assets before publishing a tagged release."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_source import allowed


def checksum(path: Path) -> None:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    sidecar = path.with_name(path.name + ".sha256")
    if sidecar.exists():
        recorded = sidecar.read_text(encoding="utf-8").split()[0]
        if recorded != digest:
            raise RuntimeError("Checksum mismatch: " + path.name)
    else:
        sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def verify(directory: Path) -> None:
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    source = list(directory.glob("*-source.zip"))
    installers = list((directory / "desktop").glob("*-setup.exe"))
    servers = list((directory / "server").glob("*.zip"))
    if len(source) != 1 or len(installers) != 1 or len(servers) != 2:
        raise RuntimeError("Release requires one source ZIP, one Windows installer and two server platform ZIPs")
    platforms = set()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    for path in source + installers + servers:
        if version not in path.name:
            raise RuntimeError("Asset version differs from project version: " + path.name)
        checksum(path)
        if path.suffix == ".exe":
            with path.open("rb") as handle:
                if handle.read(2) != b"MZ":
                    raise RuntimeError("Windows installer lacks executable header")
            if path.stat().st_size < 500_000:
                raise RuntimeError("Windows installer is unexpectedly small")
            continue
        with zipfile.ZipFile(path) as package:
            if package.testzip() is not None:
                raise RuntimeError("Archive CRC failure: " + path.name)
            names = package.namelist()
            if len(names) != len(set(names)) or any(name.startswith(("/", "\\")) or ".." in Path(name).parts for name in names):
                raise RuntimeError("Archive contains unsafe or duplicate paths")
            if path in source:
                if any(not allowed(name) for name in names):
                    raise RuntimeError("Source ZIP contains excluded local artifacts")
            else:
                manifest_names = [name for name in names if name.endswith("manifest.json") and name.count("/") <= 1]
                if len(manifest_names) != 1:
                    raise RuntimeError("Server ZIP must have exactly one package manifest")
                manifest = json.loads(package.read(manifest_names[0]))
                if manifest["version"] != version:
                    raise RuntimeError("Server manifest version mismatch")
                if manifest.get("source_commit") != commit:
                    raise RuntimeError("Server package was built from another commit")
                prefix = manifest_names[0].rsplit("/", 1)[0] + "/" if "/" in manifest_names[0] else ""
                expected = {prefix + name for name in manifest["files"]} | {manifest_names[0]}
                if set(names) != expected:
                    raise RuntimeError("Server ZIP does not match its complete file manifest")
                for name, digest in manifest["files"].items():
                    if hashlib.sha256(package.read(prefix + name)).hexdigest() != digest:
                        raise RuntimeError("Server file hash mismatch: " + name)
                platforms.add(manifest["platform"])
    if platforms != {"windows-x64", "linux-x64"}:
        raise RuntimeError("Server packages must cover Windows and Linux x64")
    print(f"Verified CaseQuarry {version}: source, Windows desktop, Windows/Linux server packages and checksums")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
