import hashlib
import os
import re
from pathlib import Path

from .security import fail


def file_hash(path: Path) -> tuple[str, int]:
    value, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return value.hexdigest(), size


class Storage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if Path(key).is_absolute() or ".." in Path(key).parts:
            fail(500, "STORAGE_KEY_INVALID", "Protected storage reference is invalid.")
        resolved = (self.root / key).resolve()
        if not resolved.is_relative_to(self.root):
            fail(500, "STORAGE_KEY_INVALID", "Protected storage reference is invalid.")
        return resolved

    def store_bytes(self, tenant_id: str, case_id: str, content: bytes, kind="objects") -> tuple[str, str, int]:
        value = hashlib.sha256(content).hexdigest()
        if not all(re.fullmatch(r"[a-f0-9-]{36}", item) for item in (tenant_id, case_id)) or kind not in {"objects", "derived", "exports"}:
            fail(500, "STORAGE_SCOPE_INVALID", "Protected storage scope is invalid.")
        key = f"{kind}/{tenant_id}/{case_id}/{value[:2]}/{value}"
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            actual, size = file_hash(path)
            if actual != value or size != len(content):
                fail(409, "INTEGRITY_FAILED", "Existing original bytes failed integrity verification.")
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        return key, value, len(content)

    def store_file(self, tenant_id: str, case_id: str, source: Path, kind="objects") -> tuple[str, str, int]:
        value, size = file_hash(source)
        key = f"{kind}/{tenant_id}/{case_id}/{value[:2]}/{value}"
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if file_hash(target) != (value, size):
                fail(409, "INTEGRITY_FAILED", "Existing original bytes failed integrity verification.")
        else:
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        return key, value, size

    def verify(self, original) -> dict:
        try:
            actual, size = file_hash(self.path(original.storage_key))
        except (FileNotFoundError, OSError):
            actual, size = None, None
        expected_size = getattr(original, "byte_size", None)
        return {"valid": actual == original.sha256 and (expected_size is None or size == expected_size), "expected_sha256": original.sha256, "actual_sha256": actual, "expected_size": expected_size, "actual_size": size}
