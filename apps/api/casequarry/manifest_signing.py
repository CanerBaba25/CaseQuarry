"""Optional Ed25519 manifests, verified against independently trusted public keys."""

import base64
import hashlib
import json
import os
import re
import stat
import struct
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SIGNATURE_SCHEMA = "casequarry-manifest-signature-v1"
MANIFEST_SCHEMAS = {"casequarry-hash-manifest-v2", "casequarry-derived-production-v2"}
SIGNATURE_NAME = "manifest.signature.json"
DOMAIN = b"CaseQuarry manifest signature v1\0"
MAX_KEY_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_SIGNATURE_BYTES = 16 * 1024
MAX_PACKAGE_FILES = 20_000
MAX_CENTRAL_DIRECTORY_BYTES = 32 * 1024 * 1024
HEX = re.compile(r"[a-f0-9]{64}")


class SigningKeyError(ValueError):
    """A configured key must never silently downgrade to unsigned operation."""


class PackageVerificationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _regular_file(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise OSError("Non-regular path")
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("Non-regular file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("File changed")
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise OSError("Non-regular path")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _read_key(path, private):
    try:
        with _regular_file(path) as source:
            if os.fstat(source.fileno()).st_size > MAX_KEY_BYTES:
                raise ValueError("Key budget")
            raw = source.read(MAX_KEY_BYTES + 1)
        label = b"PRIVATE KEY" if private else b"PUBLIC KEY"
        pattern = rb"-----BEGIN " + label + rb"-----\r?\n(?:[A-Za-z0-9+/=]+\r?\n)+-----END " + label + rb"-----\s*"
        if len(raw) > MAX_KEY_BYTES or not re.fullmatch(pattern, raw):
            raise ValueError("Key format")
        key = serialization.load_pem_private_key(raw, password=None) if private else serialization.load_pem_public_key(raw)
        if not isinstance(key, Ed25519PrivateKey if private else Ed25519PublicKey):
            raise ValueError("Key algorithm")
        return key
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        raise SigningKeyError("The signing key file is invalid or unavailable." if private else "The trusted public key file is invalid or unavailable.") from None


def load_private_signing_key(path) -> Ed25519PrivateKey | None:
    return None if path is None else _read_key(path, True)


def public_key_id(key) -> str:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    if not isinstance(public, Ed25519PublicKey):
        raise SigningKeyError("An Ed25519 key is required.")
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def signing_metadata(key):
    return {"signed": key is not None, "algorithm": "Ed25519" if key is not None else None, "key_id": public_key_id(key) if key is not None else None}


def sign_manifest(raw_manifest_bytes, key) -> dict:
    if not isinstance(raw_manifest_bytes, bytes) or not raw_manifest_bytes or len(raw_manifest_bytes) > MAX_MANIFEST_BYTES or not isinstance(key, Ed25519PrivateKey):
        raise ValueError("A bounded manifest and Ed25519 private key are required.")
    return {"schema_version": SIGNATURE_SCHEMA, "algorithm": "Ed25519", "key_id": public_key_id(key), "manifest_sha256": hashlib.sha256(raw_manifest_bytes).hexdigest(), "signature": base64.b64encode(key.sign(DOMAIN + raw_manifest_bytes)).decode("ascii")}


def _reject(code, message):
    raise PackageVerificationError(code, message)


def _unique_json(raw):
    def pairs(values):
        result = {}
        for name, value in values:
            if name in result:
                _reject("JSON_DUPLICATE_KEY", "Package JSON contains duplicate keys.")
            result[name] = value
        return result
    def constant(_value):
        _reject("JSON_INVALID", "Package JSON contains an unsupported value.")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def _canonical_path(name):
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 1024 or "\\" in name or ":" in name or any(ord(character) < 32 or ord(character) == 127 for character in name):
        return False
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}
    return all(part and part not in {".", ".."} and not part.endswith((".", " ")) and part.partition(".")[0].upper() not in reserved for part in parts)


def _central_directory_budget(source):
    """Bound the directory before ZipFile allocates/parses its member records."""
    source.seek(0, 2)
    size = source.tell()
    source.seek(max(0, size - 65_557))
    tail = source.read(65_557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or position + 22 > len(tail):
        _reject("ZIP_INVALID", "Package ZIP structure is invalid.")
    fields = struct.unpack_from("<4s4H2LH", tail, position)
    if position + 22 + fields[7] != len(tail) or fields[1] or fields[2] or fields[3] != fields[4]:
        _reject("ZIP_INVALID", "Split or invalid ZIP archives are unsupported.")
    count, directory_size = fields[4], fields[5]
    eocd_offset = size - len(tail) + position
    directory_end = eocd_offset
    if count == 0xFFFF or directory_size == 0xFFFFFFFF or fields[6] == 0xFFFFFFFF:
        if eocd_offset < 20:
            _reject("ZIP_INVALID", "Package ZIP64 structure is invalid.")
        source.seek(eocd_offset - 20)
        locator = source.read(20)
        signature, disk, offset, disks = struct.unpack("<4sLQL", locator)
        if signature != b"PK\x06\x07" or disk or disks != 1 or offset > eocd_offset - 56:
            _reject("ZIP_INVALID", "Package ZIP64 structure is invalid.")
        source.seek(offset)
        record = source.read(56)
        values = struct.unpack("<4sQ2H2L4Q", record)
        if values[0] != b"PK\x06\x06" or values[1] != 44 or offset + 56 != eocd_offset - 20 or values[4] or values[5] or values[6] != values[7]:
            _reject("ZIP_INVALID", "Split or invalid ZIP64 archives are unsupported.")
        count, directory_size = values[7], values[8]
        directory_end = offset
    if count > MAX_PACKAGE_FILES + 2 or directory_size > MAX_CENTRAL_DIRECTORY_BYTES:
        _reject("PACKAGE_LIMIT", "Package exceeds the bounded member or directory limit.")
    directory_start = directory_end - directory_size
    if directory_start < 0:
        _reject("ZIP_INVALID", "Package ZIP directory is invalid.")
    source.seek(directory_start)
    actual_count = 0
    while source.tell() < directory_end:
        header = source.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            _reject("ZIP_INVALID", "Package ZIP directory is invalid.")
        name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
        source.seek(name_size + extra_size + comment_size, 1)
        actual_count += 1
        if source.tell() > directory_end or actual_count > MAX_PACKAGE_FILES + 2:
            _reject("PACKAGE_LIMIT", "Package exceeds the bounded member or directory limit.")
    if actual_count != count:
        _reject("ZIP_INVALID", "Package ZIP member count is inconsistent.")
    source.seek(0)


def verify_signed_package(path, trusted_public_key_path, *, max_total_bytes=8 * 1024**3) -> dict:
    result = {"valid": False, "signature_valid": False, "key_id": None, "algorithm": "Ed25519", "files_checked": 0, "bytes_checked": 0}
    try:
        if not isinstance(max_total_bytes, int) or isinstance(max_total_bytes, bool) or max_total_bytes <= 0:
            _reject("PACKAGE_LIMIT", "Choose a positive package byte limit.")
        try:
            trusted = _read_key(trusted_public_key_path, False)
        except SigningKeyError:
            _reject("TRUSTED_KEY_INVALID", "The independently trusted Ed25519 public key is invalid or unavailable.")
        with _regular_file(path) as source:
            _central_directory_budget(source)
            with zipfile.ZipFile(source) as archive:
                members = archive.infolist()
                names = [member.filename for member in members]
                if len(members) > MAX_PACKAGE_FILES + 2:
                    _reject("PACKAGE_LIMIT", "Package exceeds the bounded member limit.")
                if len(set(names)) != len(names):
                    _reject("ZIP_DUPLICATE_MEMBER", "Package ZIP contains duplicate members.")
                total = 0
                for member in members:
                    mode = member.external_attr >> 16
                    if not _canonical_path(member.filename) or member.orig_filename != member.filename or member.is_dir():
                        _reject("PACKAGE_PATH_INVALID", "Package contains an unsafe or noncanonical member path.")
                    if member.flag_bits & 0x41 or member.external_attr & 0x410 or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                        _reject("PACKAGE_MEMBER_INVALID", "Encrypted, linked or unsupported ZIP members are prohibited.")
                    total += member.file_size
                    if total > max_total_bytes:
                        _reject("PACKAGE_LIMIT", "Package exceeds the total uncompressed byte limit.")
                if "manifest.json" not in names or SIGNATURE_NAME not in names:
                    _reject("SIGNATURE_MISSING", "An independently verifiable signed manifest is required.")
                if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES or archive.getinfo(SIGNATURE_NAME).file_size > MAX_SIGNATURE_BYTES:
                    _reject("PACKAGE_LIMIT", "Package manifest metadata exceeds its byte limit.")
                raw = archive.read("manifest.json")
                sidecar = _unique_json(archive.read(SIGNATURE_NAME))
                if not isinstance(sidecar, dict) or set(sidecar) != {"schema_version", "algorithm", "key_id", "manifest_sha256", "signature"} or sidecar["schema_version"] != SIGNATURE_SCHEMA or sidecar["algorithm"] != "Ed25519" or not isinstance(sidecar["key_id"], str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", sidecar["key_id"]):
                    _reject("SIGNATURE_INVALID", "Manifest signature metadata is invalid.")
                result["key_id"] = sidecar["key_id"]
                if sidecar["key_id"] != public_key_id(trusted) or sidecar["manifest_sha256"] != hashlib.sha256(raw).hexdigest():
                    _reject("SIGNATURE_INVALID", "Manifest or independently trusted signing key does not match.")
                try:
                    signature = base64.b64decode(sidecar["signature"], validate=True)
                    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != sidecar["signature"]:
                        raise ValueError("Signature encoding")
                    trusted.verify(signature, DOMAIN + raw)
                except (InvalidSignature, ValueError, TypeError):
                    _reject("SIGNATURE_INVALID", "Manifest signature could not be verified with the trusted key.")
                result["signature_valid"] = True
                manifest = _unique_json(raw)
                if not isinstance(manifest, dict) or manifest.get("schema_version") not in MANIFEST_SCHEMAS or manifest.get("algorithm") != "SHA-256":
                    _reject("MANIFEST_INVALID", "Signed package manifest type is unsupported.")
                inventory = manifest.get("package_files")
                if isinstance(inventory, dict) and any(not _canonical_path(name) for name in inventory):
                    _reject("PACKAGE_PATH_INVALID", "Signed inventory contains an unsafe or noncanonical member path.")
                if not isinstance(inventory, dict) or len(inventory) > MAX_PACKAGE_FILES or set(inventory) != set(names) - {"manifest.json", SIGNATURE_NAME}:
                    _reject("PACKAGE_INVENTORY_INVALID", "Package members do not match the complete signed inventory.")
                for name, entry in inventory.items():
                    if not _canonical_path(name) or not isinstance(entry, dict) or set(entry) != {"sha256", "byte_size"} or not isinstance(entry["sha256"], str) or not HEX.fullmatch(entry["sha256"]) or not isinstance(entry["byte_size"], int) or isinstance(entry["byte_size"], bool) or entry["byte_size"] < 0 or archive.getinfo(name).file_size != entry["byte_size"]:
                        _reject("PACKAGE_INVENTORY_INVALID", "Signed member hash or size metadata is invalid.")
                    digest, size = hashlib.sha256(), 0
                    with archive.open(name) as incoming:
                        while chunk := incoming.read(1024 * 1024):
                            size += len(chunk)
                            if size > entry["byte_size"] or result["bytes_checked"] + size > max_total_bytes:
                                _reject("PACKAGE_LIMIT", "Package stream exceeded its declared byte budget.")
                            digest.update(chunk)
                    if size != entry["byte_size"] or digest.hexdigest() != entry["sha256"]:
                        _reject("PACKAGE_HASH_MISMATCH", "Package member bytes do not match the signed inventory.")
                    result["files_checked"] += 1
                    result["bytes_checked"] += size
        result["valid"] = True
    except PackageVerificationError as error:
        result.update(error_code=error.code, error=str(error))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RuntimeError, RecursionError, struct.error, zipfile.BadZipFile, NotImplementedError):
        result.update(error_code="PACKAGE_INVALID", error="The package could not be safely verified.")
    return result
