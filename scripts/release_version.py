"""Validate product manifest versions and expose matching release filenames."""

import argparse
import ast
import json
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf8"))
    version = project["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Installable releases require a regular major.minor.patch version")
    values = {"Python package": version}
    python = ast.parse((ROOT / "apps/api/casequarry/__init__.py").read_text(encoding="utf8"))
    declaration = next((node.value for node in python.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)), None)
    if declaration is None:
        raise RuntimeError("Python runtime version is missing")
    values["Python runtime"] = ast.literal_eval(declaration)
    for application in ["web", "desktop"]:
        package = json.loads((ROOT / f"apps/{application}/package.json").read_text(encoding="utf8"))
        locked = json.loads((ROOT / f"apps/{application}/package-lock.json").read_text(encoding="utf8"))
        values[application] = package["version"]
        values[application + " lock"] = locked["version"]
        values[application + " root package lock"] = locked["packages"][""]["version"]
    values["Desktop installer"] = json.loads((ROOT / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf8"))["version"]
    values["Desktop Rust"] = tomllib.loads((ROOT / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf8"))["package"]["version"]
    values["Core Rust"] = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf8"))["workspace"]["package"]["version"]
    for filename, package in [("uv.lock", "casequarry"), ("Cargo.lock", "casequarry-evidence-core"), ("apps/desktop/src-tauri/Cargo.lock", "casequarry-desktop")]:
        lock = tomllib.loads((ROOT / filename).read_text(encoding="utf8"))
        entries = [entry["version"] for entry in lock["package"] if entry["name"] == package]
        if len(entries) != 1:
            raise RuntimeError("Product package is missing or ambiguous in " + filename)
        values[filename] = entries[0]
    mismatches = {name: value for name, value in values.items() if value != version}
    if mismatches:
        raise RuntimeError("Release manifests disagree: " + json.dumps(mismatches, sort_keys=True))
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-env", action="store_true", help="Append the validated version to the GitHub Actions environment file")
    args = parser.parse_args()
    version = release_version()
    if args.github_env:
        filename = os.environ.get("GITHUB_ENV")
        if not filename:
            parser.error("--github-env requires the GitHub Actions environment file")
        with Path(filename).open("a", encoding="utf8", newline="\n") as output:
            output.write("CASEQUARRY_RELEASE_VERSION=" + version + "\n")
    print(json.dumps({"version": version, "tag": "v" + version, "windows_archive": f"casequarry-server-{version}-windows-x64.zip", "linux_archive": f"casequarry-server-{version}-linux-x64.zip", "desktop_installer": f"CaseQuarry_{version}_x64-setup.exe", "macos_installer": f"CaseQuarry_{version}_universal.dmg", "linux_installer": f"CaseQuarry_{version}_amd64.deb"}))


if __name__ == "__main__":
    main()
