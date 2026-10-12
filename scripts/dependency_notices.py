"""Inventory locked dependencies without copying their code or claiming legal approval."""

from __future__ import annotations

import importlib.metadata
import json
import re
import tomllib
from pathlib import Path


def normalized(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def generate_notices(root: Path) -> None:
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
                    ", ".join(classifiers)
                    or (
                        license_text
                        if len(license_text) < 120
                        else "See installed distribution license files"
                    )
                    or "Metadata not declared; manual review required"
                )
            files = meta.get_all("License-File", [])
        else:
            expression, files = (
                "Not installed on the audit platform; review distribution before deployment",
                [],
            )
        python.append(
            {
                "name": name,
                "version": package["version"],
                "license_metadata": expression,
                "license_files": files,
                "source": f"https://pypi.org/project/{name}/{package['version']}/",
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
                }
            )
    inventory = {
        "scope": "uv.lock Python packages including development/platform dependencies; production npm lock packages",
        "legal_review": "pending; metadata inventory is not approval",
        "python": python,
        "javascript": javascript,
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
        "This inventory was generated from the checked-in lockfiles and installed Python package metadata. It is a review aid, not a legal compatibility determination. Platform-only packages that were not installed, ambiguous metadata, image transitives and optional model weights need separate review before public distribution.",
        "",
        "The proposed CaseQuarry license remains a draft; it does not replace third-party license rights. See [the machine-readable inventory](docs/DEPENDENCY_INVENTORY.json).",
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
    lines += [
        "",
        "Container base images and PostgreSQL are deployed as separate components. Their own distributions contain notices for bundled operating-system packages. This repository does not claim to have completed a container image license/security audit.",
        "",
    ]
    (root / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"Inventoried {len(python)} Python and {len(javascript)} production JavaScript packages; legal review remains pending."
    )


if __name__ == "__main__":
    generate_notices(Path(__file__).resolve().parents[1])
