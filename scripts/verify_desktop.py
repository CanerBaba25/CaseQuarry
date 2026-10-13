"""Verify an owned desktop distribution and its actual system WebView runtime."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_version import release_version


def captured(args: list[str], *, timeout=180, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, check=False, capture_output=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as error:
        context = tool_context(subprocess.CompletedProcess(args, 124, error.stdout, error.stderr))
        raise RuntimeError(f"{args[0]} timed out after {timeout}s: {context}") from error


def command(*args: str, **kwargs) -> subprocess.CompletedProcess:
    process = captured(list(args), **kwargs)
    if process.returncode:
        raise RuntimeError(f"{args[0]} failed ({process.returncode}): {tool_context(process)}")
    return process


def tool_context(process: subprocess.CompletedProcess) -> str:
    def decoded(value):
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
    output = decoded(process.stdout) + "\n" + decoded(process.stderr)
    return output if len(output) <= 3000 else output[:1500] + "\n[tool output middle omitted]\n" + output[-1500:]


def reviewed_apache_prompt(output: str) -> bool:
    normalized = " ".join(output.casefold().split())
    return ("apache license" in normalized and "version 2.0" in normalized
            and re.search(r"do you agree|\[y/n\]|\(y/n\)|type [\"']?y\b", normalized) is not None)


def reviewed_license_cancellation(process: subprocess.CompletedProcess, license_text: str) -> bool:
    # A noninteractive hdiutil can display the full EULA and cancel without
    # printing a Y/N prompt. The whole reviewed license, not its heading alone,
    # must be present before this alternative permits one confirmation retry.
    output = ((process.stdout or b"") + (process.stderr or b"")).decode("utf-8", errors="replace")
    normalized_license = " ".join(license_text.split())
    return (process.returncode == 1 and bool(normalized_license)
            and normalized_license in " ".join(output.split())
            and "hdiutil: attach canceled" in output.splitlines())


def attach_image(bundle: Path, mount: Path) -> bool:
    arguments = ["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(bundle)]
    process = captured(arguments, input=b"\n")
    if process.returncode == 0:
        return False
    # Tauri embeds bundle.licenseFile as a DMG EULA. Accept only our reviewed
    # Apache image license after the actual tool output identifies its prompt
    # or displays the entire reviewed text followed by the known cancellation.
    output = ((process.stdout or b"") + (process.stderr or b"")).decode("utf-8", errors="replace")
    root = Path(__file__).resolve().parents[1]
    configuration = json.loads((root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    license_file = (root / "apps/desktop/src-tauri" / configuration["bundle"]["licenseFile"]).resolve()
    license_text = license_file.read_text(encoding="utf-8")
    prompt_confirmed = reviewed_apache_prompt(output)
    cancellation_confirmed = reviewed_license_cancellation(process, license_text)
    if license_file != root / "LICENSE" or "Apache License" not in license_text or "Version 2.0" not in license_text or not (prompt_confirmed or cancellation_confirmed):
        raise RuntimeError(f"hdiutil attach failed ({process.returncode}): {tool_context(process)}")
    prompt = [line.strip() for line in output.splitlines() if re.search(r"do you agree|\[y/n\]|\(y/n\)", line, re.IGNORECASE)]
    confirmation = "agreement prompt: " + " ".join(prompt)[-600:] if prompt_confirmed else "complete license and exact attach-canceled marker"
    print("DMG displayed the reviewed Apache2.0 " + confirmation)
    command(*arguments, input=b"Y\n")
    return True


def runtime(binary: Path, directory: Path) -> dict:
    report = directory / "runtime.json"
    environment = os.environ.copy()
    environment["CASEQUARRY_DESKTOP_DIAGNOSTIC_REPORT"] = str(report)
    process = captured(
        [str(binary), "--diagnose-runtime"], env=environment, cwd=directory,
        timeout=45,
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
            accepted_license = attach_image(bundle, mount)
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
            return {"platform": platform, "architectures": sorted(architectures), "ad_hoc_signature_verified": True, "reviewed_project_license_accepted": accepted_license, "runtime": result}
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
