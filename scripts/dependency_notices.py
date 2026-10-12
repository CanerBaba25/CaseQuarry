"""Inventory locked dependencies without copying their code or claiming legal approval."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import tomllib
from pathlib import Path


def normalized(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def generate_notices(root: Path) -> None:
    platform_path = root / "docs" / "PLATFORM_LICENSE_VERIFICATION.json"
    platform_verified = (
        {(item["name"], item["version"]): item for item in json.loads(platform_path.read_text())}
        if platform_path.exists()
        else {}
    )
    installed = {
        normalized(dist.metadata.get("Name", "")): dist for dist in importlib.metadata.distributions()
    }
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    python = []
    for package in lock["package"]:
        name = package["name"]
        if name == "casequarry":
            continue
        dist = installed.get(normalized(name))
        if dist:
            meta = dist.metadata
            expression = meta.get("License-Expression", "")
            classifiers = [
                item.rsplit(" :: ", 1)[-1]
                for item in meta.get_all("Classifier", [])
                if item.startswith("License ::")
            ]
            license_text = meta.get("License", "")
            if not expression:
                expression = (
                    (license_text if 0 < len(license_text) < 120 else "")
                    or ", ".join(classifiers)
                    or (
                        license_text
                        if len(license_text) < 120
                        else "See installed distribution license files"
                    )
                    or "Metadata not declared; manual review required"
                )
            files = meta.get_all("License-File", [])
        else:
            verified = platform_verified.get((name, package["version"]))
            expression = (
                verified["license_metadata"]
                if verified
                else "Not installed on the audit platform; review distribution before deployment"
            )
            files = [entry["path"] for entry in verified["license_files"]] if verified else []
        checked_files = []
        if dist:
            for entry in dist.files or []:
                entry_path = str(entry).replace("\\", "/")
                if ".dist-info" in entry_path and ("/licenses/" in entry_path.lower() or entry.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))):
                    path = dist.locate_file(entry)
                    if path.is_file():
                        checked_files.append(
                            {
                                "path": str(entry).replace("\\", "/"),
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            }
                        )
        python.append(
            {
                "name": name,
                "version": package["version"],
                "license_metadata": expression,
                "license_files": files,
                "source": f"https://pypi.org/project/{name}/{package['version']}/",
                "checked_distribution_license_files": checked_files,
                "platform_source_verification": platform_verified.get((name, package["version"])),
            }
        )
    javascript = []
    npm_path = root / "apps/web/package-lock.json"
    if npm_path.exists():
        packages = json.loads(npm_path.read_text(encoding="utf-8")).get("packages", {})
        for path, package in sorted(packages.items()):
            if not path or package.get("dev"):
                continue
            name = path.rsplit("node_modules/", 1)[-1]
            javascript.append(
                {
                    "name": name,
                    "version": package.get("version", "unknown"),
                    "license_metadata": package.get(
                        "license", "Lockfile license not declared; manual review required"
                    ),
                    "source": f"https://www.npmjs.com/package/{name}",
                    "checked_distribution_license_files": [
                        {"path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                        for file in (root / "apps/web" / path).glob("*")
                        if file.is_file() and file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))
                    ],
                }
            )
    rust = []
    cargo_path = root / "Cargo.lock"
    cargo_sources = Path(os.getenv("CARGO_HOME", Path.home() / ".cargo")) / "registry/src"
    if cargo_path.exists():
        for package in tomllib.loads(cargo_path.read_text())["package"]:
            if not package.get("source"):
                continue
            paths = list(cargo_sources.glob(f"*/{package['name']}-{package['version']}"))
            directory = paths[0] if paths else None
            metadata = tomllib.loads((directory / "Cargo.toml").read_text()) if directory else {}
            rust.append(
                {
                    "name": package["name"],
                    "version": package["version"],
                    "license_metadata": metadata.get("package", {}).get(
                        "license", "Primary crate distribution not cached; verify before binary distribution"
                    ),
                    "source": f"https://crates.io/crates/{package['name']}/{package['version']}",
                    "primary_artifact_sha256": package.get("checksum"),
                    "checked_distribution_license_files": [
                        {"path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                        for file in directory.glob("*")
                        if file.is_file() and file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING"))
                    ]
                    if directory
                    else [],
                }
            )
    inventory = {
        "scope": "Locked Python packages incl local QA/platform dependencies; production npm lock packages; Cargo crate distributions",
        "project_license": "Apache-2.0",
        "review_scope": "Declared metadata and available primary distribution licence-file hashes checked; no bundled binary/container/model clearance claim",
        "python": python,
        "javascript": javascript,
        "rust": rust,
        "separately_deployed": [
            {
                "component": "PostgreSQL 16",
                "license_metadata": "PostgreSQL License",
                "source": "https://www.postgresql.org/about/licence/",
            },
            {
                "component": "Python 3.12",
                "license_metadata": "PSF License Agreement and bundled third-party notices",
                "source": "https://docs.python.org/3.12/license.html",
            },
            {
                "component": "Node.js 24",
                "license_metadata": "MIT and bundled third-party notices",
                "source": "https://github.com/nodejs/node/blob/main/LICENSE",
            },
        ],
    }
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "DEPENDENCY_INVENTORY.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Third-party dependencies",
        "",
        "CaseQuarry source does not include vendored dependency code. Installed libraries and container components retain their independent licenses and packaged notices. Do not remove those notices from deployments or distributions.",
        "",
        "This inventory records locked Python, production JavaScript and Rust dependencies, declared license metadata and hashes of available primary distribution license files. Linux-only Python packages were checked against hash-verified PyPI source distributions. It is a review aid, not a legal compatibility determination. Optional platform binaries, container image transitives and model weights require bundle-specific review when redistributed.",
        "",
        "CaseQuarry uses Apache-2.0. Third-party rights remain independent. See [the machine-readable inventory](docs/DEPENDENCY_INVENTORY.json) and [platform source-distribution verification](docs/PLATFORM_LICENSE_VERIFICATION.json).",
        "",
        "| Python package | Locked version | Reported license metadata |",
        "|---|---|---|",
    ]
    for package in python:
        text = package["license_metadata"].replace("|", "/").replace("\n", " ")
        lines.append(f"| [{package['name']}]({package['source']}) | {package['version']} | {text} |")
    lines += [
        "",
        "| Production JavaScript package | Locked version | Reported license metadata |",
        "|---|---|---|",
    ]
    for package in javascript:
        lines.append(
            f"| [{package['name']}]({package['source']}) | {package['version']} | {package['license_metadata']} |"
        )
    lines += ["", "| Rust crate | Locked version | Primary distribution license metadata |", "|---|---|---|"]
    for package in rust:
        lines.append(
            f"| [{package['name']}]({package['source']}) | {package['version']} | {package['license_metadata'].replace('|', '/')} |"
        )
    lines += [
        "",
        "Container base images and PostgreSQL are deployed as separate components. Their own distributions contain notices for bundled operating-system packages. This repository does not claim to have completed a container image license/security audit.",
        "",
    ]
    (root / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"Inventoried {len(python)} Python, {len(javascript)} production JavaScript and {len(rust)} Rust packages; bundle-specific obligations remain separate."
    )


if __name__ == "__main__":
    generate_notices(Path(__file__).resolve().parents[1])
