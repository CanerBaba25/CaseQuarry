"""Verify an owned desktop distribution and its actual system WebView runtime."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_version import release_version


def command(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), check=True, capture_output=True, timeout=180, **kwargs)


def runtime(binary: Path, directory: Path) -> dict:
    report = directory / "runtime.json"
    environment = os.environ.copy()
    environment["CASEQUARRY_DESKTOP_DIAGNOSTIC_REPORT"] = str(report)
    process = subprocess.run(
        [str(binary), "--diagnose-runtime"], env=environment, cwd=directory,
        capture_output=True, timeout=45, check=False,
    )
    if process.returncode != 0 or not report.is_file():
        context = (process.stderr or process.stdout).decode("utf-8", errors="replace")[-3000:]
        raise RuntimeError(f"Packaged WebView diagnostic failed ({process.returncode}): {context}")
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("passed") or result.get("version") != release_version():
        raise RuntimeError("Packaged WebView/version/preference diagnostic failed")
    return result


def verify(platform: str, bundle: Path, binary: Path | None, install: bool) -> dict:
    bundle = bundle.resolve(strict=True)
    version = release_version()
    if version not in bundle.name:
        raise RuntimeError("Desktop distribution version does not match the source")
    with tempfile.TemporaryDirectory(prefix="casequarry-desktop-verify-") as temporary:
        directory = Path(temporary)
        if platform == "windows-x64":
            if sys.platform != "win32" or bundle.suffix != ".exe" or binary is None:
                raise RuntimeError("Windows verification requires its installer and built executable")
            with bundle.open("rb") as handle:
                if handle.read(2) != b"MZ":
                    raise RuntimeError("Windows installer is not a PE executable")
            result = runtime(binary.resolve(strict=True), directory)
            return {"platform": platform, "installer_header": True, "runtime": result}

        if platform == "linux-x64":
            if sys.platform != "linux" or bundle.suffix != ".deb":
                raise RuntimeError("Linux verification requires a DEB on Ubuntu 24.04 x64")
            fields = command("dpkg-deb", "--field", str(bundle), "Package", "Version", "Architecture", text=True).stdout
            metadata = dict(line.split(": ", 1) for line in fields.splitlines() if ": " in line)
            if metadata.get("Version") != version or metadata.get("Architecture") != "amd64":
                raise RuntimeError("DEB version or architecture mismatch")
            if metadata.get("Package") != "case-quarry":
                raise RuntimeError("Unexpected desktop package identity")
            if not install:
                raise RuntimeError("Pass --install on an owned Ubuntu CI runner to verify the installed package")
            command("sudo", "apt-get", "install", "--yes", str(bundle))
            executable = Path("/usr/bin/casequarry-desktop")
            with executable.open("rb") as handle:
                header = handle.read(20)
            if header[:5] != b"\x7fELF\x02" or struct.unpack("<H", header[18:20])[0] != 62:
                raise RuntimeError("Installed desktop binary is not Linux x64")
            linked = command("ldd", str(executable), text=True).stdout
            if "not found" in linked:
                raise RuntimeError("Installed desktop binary has unresolved shared libraries")
            result = runtime(executable, directory)
            return {"platform": platform, "installed_package": metadata, "shared_libraries_resolved": True, "runtime": result}

        if platform != "macos-universal" or sys.platform != "darwin" or bundle.suffix != ".dmg":
            raise RuntimeError("macOS verification requires its Universal DMG on a Mac runner")
        mount = directory / "mount"
        mount.mkdir()
        attached = False
        try:
            command("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(bundle))
            attached = True
            applications = list(mount.glob("*.app"))
            if len(applications) != 1:
                raise RuntimeError("DMG must contain exactly one CaseQuarry application")
            application = applications[0]
            information = plistlib.loads((application / "Contents/Info.plist").read_bytes())
            if information.get("CFBundleIdentifier") != "com.casequarry.desktop" or information.get("CFBundleShortVersionString") != version:
                raise RuntimeError("Mac application identity or version differs")
            name = information.get("CFBundleExecutable", "")
            if not name or Path(name).name != name:
                raise RuntimeError("Invalid Mac application executable")
            executable = application / "Contents/MacOS" / name
            architectures = set(command("lipo", "-archs", str(executable), text=True).stdout.split())
            if architectures != {"arm64", "x86_64"}:
                raise RuntimeError("Mac application must contain Apple Silicon and Intel code")
            command("codesign", "--verify", "--deep", "--strict", str(application))
            # Launch a copied app, as users do after dragging it into Applications.
            installed = directory / application.name
            shutil.copytree(application, installed, symlinks=True)
            result = runtime(installed / "Contents/MacOS" / name, directory)
            return {"platform": platform, "architectures": sorted(architectures), "ad_hoc_signature_verified": True, "runtime": result}
        finally:
            if attached:
                command("hdiutil", "detach", str(mount))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["windows-x64", "linux-x64", "macos-universal"], required=True)
    parser.add_argument("--bundle", type=Path, help="Distribution file, or a directory containing one matching distribution")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--install", action="store_true", help="Install the DEB on an owned Ubuntu CI runner")
    parser.add_argument("--report", type=Path)
    options = parser.parse_args()
    targets = {
        "windows-x64": ("x86_64-pc-windows-msvc", "nsis", "*.exe"),
        "linux-x64": ("x86_64-unknown-linux-gnu", "deb", "*.deb"),
        "macos-universal": ("universal-apple-darwin", "dmg", "*.dmg"),
    }
    target, kind, pattern = targets[options.platform]
    release = Path("apps/desktop/src-tauri/target") / target / "release"
    distribution = options.bundle or release / "bundle" / kind
    if distribution.is_dir():
        matching = list(distribution.glob(pattern))
        if len(matching) != 1:
            raise RuntimeError("Expected exactly one desktop distribution for this platform")
        distribution = matching[0]
    if options.platform == "windows-x64" and options.binary is None:
        options.binary = release / "casequarry-desktop.exe"
    verified = verify(options.platform, distribution, options.binary, options.install)
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(json.dumps(verified, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verified))
