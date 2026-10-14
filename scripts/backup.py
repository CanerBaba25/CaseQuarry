"""Offline encrypted SQLite/storage backup and isolated, hash-verified restore.

This development utility requires stopped API/workers. PostgreSQL and online
backup coordination are deliberately outside its supported scope.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"CQBK\x01"
CHUNK = 1024 * 1024


def derive(password: str, salt: bytes) -> bytes:
    if len(password) < 16:
        raise ValueError("Use a backup passphrase of at least 16 characters")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))


def digest_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while block := source.read(CHUNK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or ":" in name
        or any(ord(char) < 32 for char in name)
    ):
        raise ValueError("Unsafe backup member path")
    if name not in {"database.sqlite", "manifest.jsonl", "backup-info.json"} and (
        not path.parts or path.parts[0] != "storage"
    ):
        raise ValueError("Unexpected backup member")
    return path


class EncryptedWriter(io.RawIOBase):
    def __init__(self, target, encryptor):
        self.target = target
        self.encryptor = encryptor

    def writable(self):
        return True

    def write(self, data):
        self.target.write(self.encryptor.update(data))
        return len(data)

    def flush(self):
        self.target.flush()


def create_backup(
    database: Path, storage: Path, output: Path, password: str, *, services_stopped: bool
) -> dict:
    if not services_stopped:
        raise ValueError("Stop API and workers before backing up; explicitly confirm services are stopped")
    if database.is_symlink() or storage.is_symlink() or not database.is_file() or not storage.is_dir():
        raise ValueError("Existing nonsymlink SQLite database and storage directory are required")
    database, storage = database.resolve(), storage.resolve()
    output = output.resolve()
    if output.is_relative_to(storage) or output == database:
        raise ValueError("Store encrypted backups outside the live evidence store")
    if output.exists():
        raise FileExistsError("Backup destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    salt, nonce = os.urandom(16), os.urandom(12)
    cipher = Cipher(algorithms.AES(derive(password, salt)), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(MAGIC + salt + nonce)
    count, total = 0, 0
    with tempfile.TemporaryDirectory(prefix="casequarry-backup-") as temporary:
        scratch = Path(temporary)
        snapshot = scratch / "database.sqlite"
        with (
            closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(snapshot)) as target,
        ):
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite snapshot failed integrity verification")
        created_output = False
        try:
            destination = output.open("xb")
            created_output = True
            with (
                destination,
                (scratch / "manifest.jsonl").open("w", encoding="utf-8") as manifest,
            ):
                if os.name != "nt":
                    output.chmod(0o600)
                destination.write(MAGIC + salt + nonce)
                with tarfile.open(fileobj=EncryptedWriter(destination, cipher), mode="w|gz") as archive:

                    def add(path: Path, name: str):
                        nonlocal count, total
                        safe_member(name)
                        if path.is_symlink() or not path.is_file():
                            raise ValueError("Backup refuses symbolic links and nonregular files")
                        before = path.stat()
                        digest, size = digest_file(path)
                        archive.add(path, arcname=name, recursive=False)
                        after = path.stat()
                        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise ValueError(
                                "A source file changed while backing up; stop all writers and retry"
                            )
                        manifest.write(json.dumps({"path": name, "sha256": digest, "bytes": size}) + "\n")
                        count += 1
                        total += size

                    add(snapshot, "database.sqlite")
                    for directory, folders, files in os.walk(storage, followlinks=False):
                        for folder in folders:
                            if (Path(directory) / folder).is_symlink():
                                raise ValueError("Backup refuses symbolic-link directories")
                        folders.sort()
                        for filename in sorted(files):
                            path = Path(directory) / filename
                            add(path, "storage/" + path.relative_to(storage).as_posix())
                    manifest.flush()
                    archive.add(scratch / "manifest.jsonl", arcname="manifest.jsonl", recursive=False)
                    info = json.dumps(
                        {
                            "format_version": 1,
                            "created_at": datetime.now(UTC).isoformat(),
                            "database": "SQLite",
                            "files": count,
                            "plaintext_bytes": total,
                            "assurance": "Offline development snapshot; isolated restore verification required",
                        }
                    ).encode()
                    member = tarfile.TarInfo("backup-info.json")
                    member.size = len(info)
                    archive.addfile(member, io.BytesIO(info))
                destination.write(cipher.finalize())
                destination.write(cipher.tag)
                destination.flush()
                os.fsync(destination.fileno())
        except Exception:
            if created_output:
                output.unlink(missing_ok=True)
            raise
    digest, encrypted_bytes = digest_file(output)
    return {
        "state": "created",
        "files": count,
        "plaintext_bytes": total,
        "encrypted_bytes": encrypted_bytes,
        "sha256": digest,
        "encryption": "AES-256-GCM with scrypt passphrase derivation",
        "restore_verified": False,
    }


def restore_backup(backup: Path, target: Path, password: str, *, max_bytes: int = 64 * 1024**3) -> dict:
    backup = backup.resolve()
    target = target.absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(
            "Restore target must be a new isolated directory; existing data is never overwritten"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".casequarry-restore-", dir=target.parent) as temporary:
        scratch = Path(temporary)
        decrypted = scratch / "archive.tar.gz"
        with backup.open("rb") as source, decrypted.open("wb") as destination:
            header = source.read(len(MAGIC) + 16 + 12)
            if len(header) != len(MAGIC) + 28 or not header.startswith(MAGIC):
                raise ValueError("Unsupported or truncated backup format")
            salt, nonce = header[len(MAGIC) : len(MAGIC) + 16], header[-12:]
            source.seek(-16, os.SEEK_END)
            tag = source.read(16)
            cipher = Cipher(algorithms.AES(derive(password, salt)), modes.GCM(nonce, tag)).decryptor()
            cipher.authenticate_additional_data(header)
            remaining = source.tell() - len(header) - 16
            source.seek(len(header))
            while remaining:
                data = source.read(min(CHUNK, remaining))
                if not data:
                    raise ValueError("Truncated encrypted backup")
                destination.write(cipher.update(data))
                remaining -= len(data)
            try:
                destination.write(cipher.finalize())
            except InvalidTag as error:
                raise ValueError(
                    "Backup authentication failed: wrong passphrase or modified bytes"
                ) from error
        restored = scratch / "restored"
        restored.mkdir(mode=0o700)
        count, total = 0, 0
        with tarfile.open(decrypted, mode="r|gz") as archive:
            for member in archive:
                relative = safe_member(member.name)
                if not member.isfile() or member.size < 0 or total + member.size > max_bytes:
                    raise ValueError("Nonregular or oversized restore member refused")
                destination = restored.joinpath(*relative.parts)
                if not destination.resolve().is_relative_to(restored.resolve()):
                    raise ValueError("Restore path escapes its isolated directory")
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(member) as source, destination.open("xb") as output:
                    if os.name != "nt":
                        destination.chmod(0o600)
                    copied = 0
                    while data := source.read(CHUNK):
                        output.write(data)
                        copied += len(data)
                if copied != member.size:
                    raise ValueError("Restore member length mismatch")
                total += copied
                if member.name not in {"manifest.jsonl", "backup-info.json"}:
                    count += 1
        verified = 0
        check_path = scratch / "manifest-check.sqlite"
        with (
            closing(sqlite3.connect(check_path)) as index,
            (restored / "manifest.jsonl").open(encoding="utf-8") as manifest,
        ):
            index.execute("CREATE TABLE verified (path TEXT PRIMARY KEY)")
            for line in manifest:
                entry = json.loads(line)
                path = safe_member(entry["path"])
                if entry["path"] in {"manifest.jsonl", "backup-info.json"}:
                    raise ValueError("Invalid manifest self-reference")
                index.execute("INSERT INTO verified(path) VALUES (?)", (entry["path"],))
                if digest_file(restored.joinpath(*path.parts)) != (entry["sha256"], entry["bytes"]):
                    raise ValueError("Restored file hash or length does not match backup manifest")
                verified += 1
        if verified != count:
            raise ValueError("Restore manifest does not cover every restored data file")
        with closing(sqlite3.connect((restored / "database.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Restored SQLite database failed integrity verification")
        os.replace(restored, target)
    return {
        "state": "verified_isolated_restore",
        "files_verified": verified,
        "plaintext_bytes": total,
        "database_integrity": "ok",
        "notice": "This is an isolated restore; no running application was changed. Review configuration and invalidate old sessions before operational recovery.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--db", type=Path, required=True)
    create.add_argument("--storage", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--confirm-services-stopped", action="store_true")
    restore = sub.add_parser("restore-verify")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--max-bytes", type=int, default=64 * 1024**3)
    args = parser.parse_args()
    password = os.getenv("CASEQUARRY_BACKUP_PASSPHRASE") or getpass.getpass(
        "Backup passphrase (never logged): "
    )
    try:
        if args.command == "create":
            result = create_backup(
                args.db, args.storage, args.output, password, services_stopped=args.confirm_services_stopped
            )
        else:
            result = restore_backup(args.backup, args.target, password, max_bytes=args.max_bytes)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, sqlite3.Error, tarfile.TarError) as error:
        parser.exit(8, f"Backup/restore failed: {error}\n")


if __name__ == "__main__":
    main()
