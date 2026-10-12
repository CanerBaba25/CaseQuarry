import sqlite3

import pytest

from scripts.backup import create_backup, restore_backup, safe_member

PASSPHRASE = "Synthetic recovery passphrase 2026!"


def fixture(tmp_path):
    database = tmp_path / "live.db"
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "original.eml").write_bytes(b"Private synthetic original bytes must not appear in ciphertext")
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, note TEXT)")
        db.execute("INSERT INTO records VALUES (1, 'Synthetic private database record')")
    return database, storage


def test_encrypted_backup_round_trip_verifies_all_hashes_and_database(tmp_path):
    database, storage = fixture(tmp_path)
    output = tmp_path / "encrypted.cqbackup"
    result = create_backup(database, storage, output, PASSPHRASE, services_stopped=True)
    assert result["files"] == 2
    assert result["restore_verified"] is False
    assert b"Private synthetic original" not in output.read_bytes()
    assert b"Synthetic private database" not in output.read_bytes()
    restored = tmp_path / "isolated"
    verified = restore_backup(output, restored, PASSPHRASE)
    assert verified["files_verified"] == 2
    assert (restored / "storage/original.eml").read_bytes() == (storage / "original.eml").read_bytes()
    with sqlite3.connect(restored / "database.sqlite") as db:
        assert db.execute("SELECT note FROM records").fetchone()[0] == "Synthetic private database record"


@pytest.mark.parametrize("tamper", [False, True])
def test_bad_password_or_ciphertext_never_publishes_a_restore(tmp_path, tamper):
    database, storage = fixture(tmp_path)
    output = tmp_path / "encrypted.cqbackup"
    create_backup(database, storage, output, PASSPHRASE, services_stopped=True)
    if tamper:
        content = bytearray(output.read_bytes())
        content[len(content) // 2] ^= 1
        output.write_bytes(content)
    target = tmp_path / "restore"
    with pytest.raises(ValueError, match="authentication failed"):
        restore_backup(output, target, PASSPHRASE if tamper else "Wrong synthetic passphrase!")
    assert not target.exists()


def test_quiescence_and_restore_overwrite_are_refused(tmp_path):
    database, storage = fixture(tmp_path)
    output = tmp_path / "encrypted.cqbackup"
    with pytest.raises(ValueError, match="Stop API"):
        create_backup(database, storage, output, PASSPHRASE, services_stopped=False)
    create_backup(database, storage, output, PASSPHRASE, services_stopped=True)
    with pytest.raises(FileExistsError):
        restore_backup(output, storage, PASSPHRASE)


@pytest.mark.parametrize(
    "name",
    ["../escape", "/absolute", "storage/../../escape", "storage\\escape", "C:/escape", "unapproved.txt"],
)
def test_restore_member_paths_are_bounded(name):
    with pytest.raises(ValueError):
        safe_member(name)


def test_restore_quota_refuses_expansion_without_publishing(tmp_path):
    database, storage = fixture(tmp_path)
    output = tmp_path / "encrypted.cqbackup"
    create_backup(database, storage, output, PASSPHRASE, services_stopped=True)
    target = tmp_path / "restore"
    with pytest.raises(ValueError, match="oversized"):
        restore_backup(output, target, PASSPHRASE, max_bytes=10)
    assert not target.exists()
