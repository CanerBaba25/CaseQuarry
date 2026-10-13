"""Build an installable API/worker and Next standalone central-server ZIP."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

if __package__:
    from .release_version import release_version
    from .server_runtime_licenses import preserve_runtime_sources
else:
    from release_version import release_version
    from server_runtime_licenses import preserve_runtime_sources

ROOT = Path(__file__).resolve().parents[1]


def run(arguments, *, env=None, capture=False):
    result = subprocess.run([str(value) for value in arguments], cwd=ROOT, env=env, stdout=subprocess.PIPE if capture else None, check=True)
    return result.stdout if capture else None


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def copy_tree(source, destination):
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Server packages refuse symlinks: " + str(path.relative_to(source)))
        if path.is_file():
            relative = path.relative_to(source)
            if any(part in {".git", "tests", "__tests__", "cache", "__pycache__"} for part in relative.parts) or path.name.startswith(".env"):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def build(args):
    actual = "windows-x64" if os.name == "nt" else "linux-x64" if platform.system() == "Linux" else None
    if actual != args.platform or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Build on the requested platform; native Node dependencies cannot be relabeled across operating systems.")
    version = release_version()
    if not args.skip_web_build:
        run(["npm.cmd" if os.name == "nt" else "npm", "--prefix", "apps/web", "run", "build"], env={**os.environ, "CASEQUARRY_API_INTERNAL_URL": "http://127.0.0.1:8000", "NEXT_TELEMETRY_DISABLED": "1"})
    standalone = ROOT / "apps/web/.next/standalone"
    application = Path("apps/web") if (standalone / "apps/web/server.js").is_file() else Path(".")
    if not (standalone / application / "server.js").is_file():
        raise RuntimeError("Build the Next standalone application before packaging.")
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"casequarry-server-{version}-{args.platform}"
    with tempfile.TemporaryDirectory(prefix="casequarry-server-build-") as temporary:
        package = Path(temporary) / name
        package.mkdir()
        run(["uv", "build", "--wheel", "--out-dir", package / "wheels"])
        requirements = run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt", "--no-annotate", "--no-header"], capture=True)
        (package / "requirements.txt").write_bytes(requirements)
        for path in (ROOT / "infra/server").iterdir():
            if path.is_file() and (path.suffix in {".py", ".ps1", ".sh"} or path.name == "Caddyfile"):
                shutil.copyfile(path, package / path.name)
        copy_tree(standalone, package / "web")
        copy_tree(ROOT / "apps/web/.next/static", package / "web" / application / ".next/static")
        if (ROOT / "apps/web/public").exists():
            copy_tree(ROOT / "apps/web/public", package / "web" / application / "public")
        for name in ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]:
            shutil.copyfile(ROOT / name, package / name)
        copy_tree(ROOT / "infra/deploy", package / "deployment")
        notices = []
        for metadata_path in sorted((package / "web").rglob("package.json")):
            metadata = json.loads(metadata_path.read_text(encoding="utf8"))
            dependency, dependency_version = metadata.get("name"), metadata.get("version")
            if not dependency or not dependency_version or dependency.startswith("casequarry"):
                continue
            source = ROOT / "apps/web/node_modules" / dependency
            files = []
            if source.is_dir():
                for entry in source.rglob("*"):
                    if entry.is_file() and (entry.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")) or any(part.lower() in {"license", "licenses"} for part in entry.relative_to(source).parts)):
                        target = package / "runtime-licenses/npm" / (dependency.replace("/", "_") + "-" + dependency_version) / entry.relative_to(source)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(entry, target)
                        files.append(target.relative_to(package).as_posix())
            repository = metadata.get("repository")
            repository = repository.get("url") if isinstance(repository, dict) else repository
            notices.append({"name": dependency, "version": dependency_version, "declared_license": metadata.get("license"), "upstream_repository": repository, "upstream_distribution": f"https://www.npmjs.com/package/{dependency}/v/{dependency_version}", "preserved_license_files": files})
        preserve_runtime_sources(package, args.platform, notices)
        (package / "runtime-licenses").mkdir(exist_ok=True)
        (package / "runtime-licenses/inventory.json").write_text(json.dumps(notices, indent=2) + "\n", encoding="utf8")
        shutil.copyfile(ROOT / "docs/SERVER_INSTALL.md", package / "INSTALL.md")
        commit = run(["git", "rev-parse", "HEAD"], capture=True).decode().strip()
        manifest = {"format": 1, "version": version, "platform": args.platform, "source_commit": commit, "web_entry": (Path("web") / application / "server.js").as_posix(), "prerequisites": ["Python3.12 or uv", "Node20.9+", "PostgreSQL16+ server/client tools; or an operator-provided PostgreSQL URL", "HTTPS reverse proxy for multi-computer firm access"], "database": "postgresql", "files": {path.relative_to(package).as_posix(): digest(path) for path in sorted(package.rglob("*")) if path.is_file()}}
        (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
        destination = directory / (package.name + ".zip")
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(package.name + "/" + path.relative_to(package).as_posix(), (2026, 10, 12, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = (0o100755 if path.suffix == ".sh" else 0o100644) << 16
                    archive.writestr(info, path.read_bytes())
        checksum = digest(destination)
        destination.with_suffix(".zip.sha256").write_text(f"{checksum}  {destination.name}\n", encoding="utf8")
        print(json.dumps({"archive": str(destination), "sha256": checksum, "files": len(manifest["files"]), "version": version, "platform": args.platform}))
        return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=["windows-x64", "linux-x64"])
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".release-artifacts/server")
    parser.add_argument("--skip-web-build", action="store_true", help="Use the standalone output just built from the same reviewed checkout.")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
