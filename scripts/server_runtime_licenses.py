"""Preserve the standalone image runtime's notices and matching upstream sources."""

import concurrent.futures
import hashlib
import json
import shutil
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "docs/SERVER_RUNTIME_SOURCES.json"
MAX_DOWNLOAD = 100 * 1024 * 1024


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(entry, cache):
    filename = entry["filename"]
    if Path(filename).name != filename or "\\" in filename:
        raise RuntimeError("Invalid upstream source filename")
    target = cache / filename
    if target.is_file() and file_digest(target) == entry["sha256"]:
        return target
    url = urllib.parse.urlsplit(entry["url"])
    if url.scheme != "https" or url.username or url.password:
        raise RuntimeError("Upstream source downloads require HTTPS without credentials")
    partial = target.with_name(target.name + ".partial")
    try:
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "CaseQuarry-source-preservation/1"})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as stream:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise RuntimeError("Upstream source exceeds the bounded download size")
                stream.write(chunk)
        if file_digest(partial) != entry["sha256"] or partial.stat().st_size != entry["bytes"]:
            raise RuntimeError("Upstream source hash/size mismatch: " + entry["component"])
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def preserve_archive_notices(source, destination):
    """Read regular notice files only; never extract or execute source archive paths."""
    total = 0
    with tarfile.open(source, "r:*") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError("Unsafe path in upstream source archive")
            if not member.isfile() or not path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE", "PATENTS", "FTL.TXT")):
                continue
            if member.size > 1024 * 1024:
                raise RuntimeError("Unbounded upstream notice file")
            total += member.size
            if total > 20 * 1024 * 1024:
                raise RuntimeError("Unbounded upstream archive notices")
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError("Unreadable upstream notice")
            with stream:
                data = stream.read(member.size + 1)
            if len(data) != member.size:
                raise RuntimeError("Invalid upstream notice size")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def preserve_runtime_sources(package, platform, dependencies):
    recipe = json.loads(RECIPE.read_text(encoding="utf8"))
    native = [item for item in dependencies if item["name"].startswith("@img/sharp-")]
    if not native:
        return
    images = [item for item in dependencies if item["name"] == "sharp"]
    if len(images) != 1 or images[0]["version"] != recipe["sharp_version"]:
        raise RuntimeError("Review the runtime source recipe for this sharp version before packaging")
    components = {item["component"]: item["version"] for item in recipe["sources"]}
    for dependency in native:
        expected = recipe["libvips_package_version"] if "-libvips-" in dependency["name"] else recipe["sharp_version"]
        if dependency["version"] != expected:
            raise RuntimeError("Native image package changed; review its corresponding source")
        source = ROOT / "apps/web/node_modules" / dependency["name"]
        if not source.is_dir() or not (source / "README.md").is_file():
            raise RuntimeError("Missing upstream native package notices: " + dependency["name"])
        notice_target = package / "runtime-licenses/npm" / (dependency["name"].replace("/", "_") + "-" + dependency["version"])
        for filename in ["README.md", "versions.json"]:
            original = source / filename
            if original.is_file():
                notice_target.mkdir(parents=True, exist_ok=True)
                target = notice_target / filename
                shutil.copyfile(original, target)
                dependency["preserved_license_files"].append(target.relative_to(package).as_posix())
        version_path = source / "versions.json"
        if not version_path.is_file():
            if dependency["name"] in {"@img/sharp-linux-x64", "@img/sharp-linuxmusl-x64"}:
                continue  # Linux addon metadata lives in its separate libvips package.
            raise RuntimeError("Missing native image component version manifest")
        versions = json.loads(version_path.read_text(encoding="utf8"))
        for component, version in versions.items():
            if component == "emscripten":
                if version != recipe["emscripten_version"]:
                    raise RuntimeError("WASM toolchain version changed; review its source recipe")
            elif components.get(component) != version:
                raise RuntimeError("Bundled native component changed: " + component)
    cache = ROOT / ".release-artifacts/server-runtime-sources"
    cache.mkdir(parents=True, exist_ok=True)
    entries = [entry for entry in recipe["sources"] if platform in entry["platforms"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        archives = list(pool.map(lambda entry: download(entry, cache), entries))
    source_directory = package / "runtime-sources"
    source_directory.mkdir()
    for entry, archive in zip(entries, archives, strict=True):
        shutil.copyfile(archive, source_directory / entry["filename"])
        if ".tar." in entry["filename"]:
            preserve_archive_notices(archive, package / "runtime-licenses/upstream" / entry["component"])
        elif entry["component"] in {"GPL-3.0", "LGPL-3.0"}:
            shutil.copyfile(archive, package / "runtime-licenses" / (entry["component"] + ".txt"))
    (source_directory / "inventory.json").write_text(json.dumps({**recipe, "sources": entries}, indent=2) + "\n", encoding="utf8")
    shutil.copyfile(ROOT / "docs/SERVER_RUNTIME_SOURCE_ACCESS.md", package / "runtime-licenses/SOURCE_ACCESS.md")
