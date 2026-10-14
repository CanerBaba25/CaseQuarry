"""Offline signing-key creation and verification with an explicit trust anchor."""

import os
import stat
import subprocess
from contextlib import ExitStack
from pathlib import Path
from typing import Annotated

import typer

from .client import fail


def _destination(value: Path) -> Path:
    path = value.expanduser().absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Signing-key destinations cannot use filesystem aliases")
    if path.exists():
        raise FileExistsError(path)
    if not path.parent.is_dir():
        raise OSError("Signing-key parent directories must already exist")
    return path


def _identity(info) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _cleanup(owned: list[tuple[Path, tuple[int, int]]]) -> list[str]:
    failures = []
    for path, identity in owned:
        try:
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and _identity(info) == identity:
                path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            failures.append(path.name)
    return failures


def create_keypair(private_path: Path, public_path: Path) -> dict:
    from casequarry.local_postgres import protect
    from casequarry.manifest_signing import public_key_id
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_path, public_path = _destination(private_path), _destination(public_path)
    if private_path == public_path:
        raise ValueError("Choose different private and public key files")
    key = Ed25519PrivateKey.generate()
    values = (
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()),
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo),
    )
    owned = []
    try:
        with ExitStack() as stack:
            streams = []
            for path in (private_path, public_path):
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                stream = stack.enter_context(os.fdopen(descriptor, "wb"))
                identity = _identity(os.fstat(stream.fileno()))
                owned.append((path, identity))
                if _identity(path.lstat()) != identity:
                    raise OSError("Signing-key destination changed during creation")
                # Establish Windows ACLs before writing any private key material.
                protect(path)
                if _identity(path.lstat()) != identity:
                    raise OSError("Signing-key destination changed during protection")
                streams.append(stream)
            for stream, value in zip(streams, values, strict=True):
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException as error:
        failures = _cleanup(owned)
        if failures:
            error.add_note("Incomplete key files could not be removed: " + ", ".join(failures))
        raise
    return {
        "algorithm": "Ed25519", "key_id": public_key_id(key),
        "private_key_file": str(private_path), "public_key_file": str(public_path),
        "overwritten_files": 0,
    }


def register(evidence, exports) -> None:
    @exports.command("signing-key-create")
    def signing_key_create(
        ctx: typer.Context,
        private_key_file: Annotated[Path, typer.Option()],
        public_key_file: Annotated[Path, typer.Option()],
    ) -> None:
        """Create a new owner-private Ed25519 key pair without overwriting files."""
        from .main import show

        try:
            private_path, public_path = _destination(private_key_file), _destination(public_key_file)
            if private_path == public_path:
                raise ValueError("Choose different private and public key files")
            if ctx.obj.dry_run:
                show({"dry_run": True, "private_key_file": str(private_path),
                      "public_key_file": str(public_path), "writes": 0}, ctx.obj)
                return
            show(create_keypair(private_path, public_path), ctx.obj)
        except FileExistsError:
            fail("A signing-key destination already exists. Existing files were preserved.", 5)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            message = "Signing-key creation failed. Use regular files in an existing writable directory."
            if getattr(error, "__notes__", None):
                message += " Incomplete files remain at the selected paths; inspect them before retrying."
            fail(message, 4)

    @evidence.command("verify-package")
    def verify_package(
        ctx: typer.Context,
        path: Annotated[Path, typer.Option()],
        trusted_public_key: Annotated[Path, typer.Option()],
        max_total_bytes: Annotated[int, typer.Option(min=1)] = 8 * 1024**3,
    ) -> None:
        """Verify a signed ZIP and all members against an independently trusted key."""
        from casequarry.manifest_signing import verify_signed_package

        from .main import show

        try:
            result = verify_signed_package(path, trusted_public_key, max_total_bytes=max_total_bytes)
        except (OSError, ValueError, TypeError):
            fail("The signed package or trusted Ed25519 public key is unavailable or invalid.", 8)
        show(result, ctx.obj)
        if not result["valid"]:
            raise typer.Exit(8)
