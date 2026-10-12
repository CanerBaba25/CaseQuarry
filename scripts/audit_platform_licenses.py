"""Check exact platform-only Python source distributions against PyPI SHA-256.

Reads licence/metadata files from authenticated download hashes without extracting
or executing third-party source. No evidence or credentials are transmitted.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

PACKAGES = {"jeepney": "0.9.0", "secretstorage": "3.5.0", "uvloop": "0.23.0"}


def fetch(url: str) -> bytes:
    if not url.startswith(("https://pypi.org/", "https://files.pythonhosted.org/")):
        raise ValueError("Unexpected dependency audit origin")
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("Dependency source archive exceeds audit budget")
    return data


def audit(root: Path) -> None:
    results = []
    for name, version in PACKAGES.items():
        info = json.loads(fetch(f"https://pypi.org/pypi/{name}/{version}/json"))
        distribution = next(item for item in info["urls"] if item["packagetype"] == "sdist")
        data = fetch(distribution["url"])
        digest = hashlib.sha256(data).hexdigest()
        if digest != distribution["digests"]["sha256"]:
            raise ValueError("Primary package source distribution hash mismatch")
        files = []
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive:
                leaf = member.name.rsplit("/", 1)[-1].upper()
                if (
                    member.isfile()
                    and member.size <= 512 * 1024
                    and leaf.startswith(("LICENSE", "LICENCE", "COPYING"))
                ):
                    value = archive.extractfile(member).read()
                    files.append(
                        {
                            "path": member.name,
                            "sha256": hashlib.sha256(value).hexdigest(),
                            "bytes": len(value),
                        }
                    )
        if not files:
            raise ValueError("Primary distribution has no recognized licence file")
        metadata = info["info"]
        expression = metadata.get("license_expression") or metadata.get("license")
        if not expression or len(expression) > 200:
            expression = (
                ", ".join(
                    value.rsplit(" :: ", 1)[-1]
                    for value in metadata.get("classifiers", [])
                    if value.startswith("License ::")
                )
                or "Manual licence interpretation required"
            )
        results.append(
            {
                "name": name,
                "version": version,
                "license_metadata": expression,
                "primary_source": distribution["url"],
                "primary_artifact_sha256": digest,
                "license_files": files,
                "verification": "Exact PyPI release source hash and licence-file presence verified; no code executed",
            }
        )
        print(f"Verified primary source and licence files: {name} {version}: {expression}")
    cache = root / ".data" / "dependency-audit"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "platform-licenses.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (root / "docs" / "PLATFORM_LICENSE_VERIFICATION.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    audit(Path(__file__).resolve().parents[1])
