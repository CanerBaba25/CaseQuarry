"""Identify a native compiler cache and remove only current app-package outputs."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "windows-x64": ["x86_64-pc-windows-msvc"],
    "linux-x64": ["x86_64-unknown-linux-gnu"],
    "macos-universal": ["x86_64-apple-darwin", "aarch64-apple-darwin"],
}


def identify() -> None:
    image = os.environ.get("ImageVersion", "unspecified")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", image):
        raise RuntimeError("Unexpected hosted runner image identity")
    destination = os.environ.get("GITHUB_ENV")
    if not destination:
        raise RuntimeError("Cache identity requires the GitHub Actions environment file")
    with Path(destination).open("a", encoding="utf-8", newline="\n") as output:
        output.write("CASEQUARRY_CACHE_IMAGE_VERSION=" + image + "\n")
    print("Compiler cache runner image: " + image)


def validate_bundle(path: Path, target: Path) -> None:
    resolved = path.resolve()
    if resolved != path or not resolved.is_relative_to(target):
        raise RuntimeError("Refusing to clean a redirected or out-of-target bundle directory")
    for part in (path, *path.parents):
        if part == target:
            break
        if (part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
                or (part.exists() and not part.is_dir())):
            raise RuntimeError("Refusing to clean an unexpected bundle directory")


def clean(platform: str, dry_run: bool = False) -> None:
    target = ROOT / "apps/desktop/src-tauri/target"
    resolved = target.resolve()
    if (resolved != target or not resolved.is_relative_to(ROOT) or target.is_symlink()
            or (target.exists() and not target.is_dir())
            or (hasattr(target, "is_junction") and target.is_junction())):
        raise RuntimeError("Refusing to clean a redirected or out-of-workspace build directory")
    bundle_targets = [target, *(target / architecture for architecture in TARGETS[platform])]
    if platform == "macos-universal":
        bundle_targets.append(target / "universal-apple-darwin")
    bundles = [directory / "release/bundle" for directory in bundle_targets]
    for bundle in bundles:
        validate_bundle(bundle, target)
    cargo = shutil.which("cargo")
    if not cargo:
        raise RuntimeError("Rust Cargo is required on PATH")
    arguments = [cargo, "clean", "--locked", "--manifest-path", str(ROOT / "apps/desktop/src-tauri/Cargo.toml"),
                 "--target-dir", str(target), "--package", "casequarry-desktop"]
    if dry_run:
        arguments.append("--dry-run")
    # Shared dependency objects remain cached; current source/assets are rebuilt.
    for architecture in [None, *TARGETS[platform]]:
        command = arguments if architecture is None else [*arguments, "--target", architecture]
        subprocess.run(command, check=True, cwd=ROOT)
    # Cargo package cleanup does not remove Tauri installers from older versions.
    for bundle in bundles:
        validate_bundle(bundle, target)
        if bundle.is_dir():
            if dry_run:
                print("Would remove generated bundle directory: " + str(bundle))
            else:
                shutil.rmtree(bundle)
    print("Checked app-package output scope" if dry_run else "Removed only the app package's host/build outputs and generated bundles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identify", action="store_true")
    parser.add_argument("--clean", choices=TARGETS)
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()
    if options.identify:
        identify()
    elif options.clean:
        clean(options.clean, options.dry_run)
    else:
        parser.error("Choose --identify or --clean PLATFORM")
