"""Explicit-scope acquisition helpers. IMAP never changes remote flags or folders."""

import hashlib
import imaplib
import json
import os
import re
import ssl
from contextlib import ExitStack
from urllib.parse import quote

from .client import API, fail


class AcquisitionError(ValueError):
    pass


def folder_inventory(path, recursive=False, maildir=False, maximum=2000, byte_limit=512 * 1024 * 1024):
    root = path.resolve()
    if not root.is_dir() or path.is_symlink() or path.is_junction():
        raise AcquisitionError("Select a real local directory; symlink roots are refused.")
    pending, rows, total, visited = [root], [], 0, 0
    while pending:
        directory = pending.pop()
        visited += 1
        if visited > maximum:
            raise AcquisitionError("Directory inventory limit exceeded; narrow the selected folder.")
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink() or entry.is_junction() or not entry.resolve().is_relative_to(root):
                continue
            if entry.is_dir():
                if recursive or (maildir and directory == root and entry.name in {"cur", "new"}):
                    pending.append(entry)
                    if len(pending) > maximum:
                        raise AcquisitionError("Directory inventory limit exceeded; narrow the selected folder.")
                continue
            if not entry.is_file() or (maildir and entry.parent.name not in {"cur", "new"}):
                continue
            size = entry.stat().st_size
            total += size
            if size < 1 or len(rows) >= maximum or total > byte_limit:
                raise AcquisitionError("File count/byte limits exceeded or an empty file was encountered; narrow the scope.")
            rows.append({"path": entry, "relative_path": entry.relative_to(root).as_posix(), "byte_size": size})
    return rows


def upload_folder(options, rows, case_id, source_label, custodian, maildir=False):
    api = API(options)
    route = api.case_route(case_id, "/imports")
    if options.dry_run:
        return {"dry_run": True, "items": [{key: value for key, value in row.items() if key != "path"} for row in rows], "file_count": len(rows)}
    if not rows:
        raise AcquisitionError("No files were selected for import.")
    custodian_id = None
    if custodian:
        custodian_id = api.request("POST", api.case_route(case_id, "/custodians"), json={"display_name": custodian})["id"]
    source = api.request("POST", api.case_route(case_id, "/sources"), json={"label": source_label, "kind": "maildir" if maildir else "local-folder", "custodian_id": custodian_id})
    batches = []
    for start in range(0, len(rows), 25):
        group = rows[start:start + 25]
        with ExitStack() as stack:
            files, paths = [], {}
            for row in group:
                name = row["relative_path"] + (".eml" if maildir else "")
                if row["path"].is_symlink() or row["path"].stat().st_size != row["byte_size"]:
                    raise AcquisitionError("An inventoried file changed before upload; inventory the scope again.")
                files.append(("files", (name, stack.enter_context(row["path"].open("rb")), "application/octet-stream")))
                paths[name] = row["relative_path"]
            batches.append(api.request("POST", route, files=files, data={"source_id": source["id"], "source_paths": json.dumps(paths)}))
    return {"items": batches, "file_count": len(rows)}


class BoundedIMAP(imaplib.IMAP4_SSL):
    def __init__(self, host, port, context, timeout, max_literal):
        self.byte_budget = 2 * 1024 * 1024
        self.max_literal = max_literal
        super().__init__(host, port, ssl_context=context, timeout=timeout)

    def read(self, size):
        if size > self.max_literal or size > self.byte_budget:
            raise imaplib.IMAP4.abort("IMAP response exceeds the configured literal/operation bound")
        self.byte_budget -= size
        return super().read(size)

    def readline(self):
        line = super().readline()
        self.byte_budget -= len(line)
        if self.byte_budget < 0:
            raise imaplib.IMAP4.abort("IMAP response exceeds the configured operation bound")
        return line


class Mailbox:
    def __init__(self, host, username, password, mailbox, port=993, ca_file=None, max_message_bytes=16 * 1024 * 1024):
        if not host or any(char.isspace() for char in host) or any(char in host for char in "/@\\"):
            raise AcquisitionError("Use an explicit IMAPS hostname without credentials or a URL path.")
        if not mailbox or len(mailbox) > 500 or any(ord(char) < 32 for char in mailbox):
            raise AcquisitionError("Select one explicit mailbox without control characters.")
        if not mailbox.isascii() or not username.isascii() or any(ord(char) < 32 for char in username):
            raise AcquisitionError("Use the server's encoded ASCII mailbox and login identifier; Unicode mailbox names require an IMAP modified-UTF7 name.")
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.host, self.username, self.mailbox, self.port = host, username, mailbox, port
        self.max_message_bytes = max_message_bytes
        self.connection = BoundedIMAP(host, port, context, 30, max_message_bytes + 1024)
        try:
            self.connection.login('"' + username.replace("\\", "\\\\").replace('"', '\\"') + '"', password)
            self.connection.byte_budget = 2 * 1024 * 1024
            status, _ = self.connection.select('"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"', readonly=True)
            if status != "OK":
                raise AcquisitionError("The explicitly selected mailbox is unavailable.")
            values = self.connection.response("UIDVALIDITY")[1]
            self.uidvalidity = str(int(values[0])) if values and values[0] else None
            if not self.uidvalidity:
                raise AcquisitionError("Mailbox did not provide UIDVALIDITY; stable acquisition cannot continue.")
        except Exception:
            self.close()
            raise

    def close(self):
        try:
            self.connection.shutdown()
        except (OSError, imaplib.IMAP4.error):
            pass

    def inventory(self, after_uid, maximum):
        self.connection.byte_budget = 1_000_000
        status, data = self.connection.uid("SEARCH", None, "UID", f"{after_uid + 1}:*")
        if status != "OK":
            raise AcquisitionError("Read-only UID inventory failed.")
        values = [int(value) for value in b" ".join(value for value in data if isinstance(value, bytes)).split()]
        selected = sorted({value for value in values if value > after_uid})[:maximum]
        rows = []
        for uid in selected:
            self.connection.byte_budget = 32 * 1024
            status, response = self.connection.uid("FETCH", str(uid), "(UID RFC822.SIZE INTERNALDATE FLAGS)")
            if status != "OK":
                raise AcquisitionError("Read-only metadata fetch failed.")
            raw = b" ".join(value for value in response if isinstance(value, bytes))
            size = re.search(rb"RFC822.SIZE\s+(\d+)", raw, re.IGNORECASE)
            returned_uids = set(re.findall(rb"\bUID\s+(\d+)", raw, re.IGNORECASE))
            if not size or returned_uids != {str(uid).encode()}:
                raise AcquisitionError("Mailbox did not return an explicit RFC822 size.")
            rows.append({"uid": uid, "byte_size": int(size[1]), "uidvalidity": self.uidvalidity, "within_message_limit": int(size[1]) <= self.max_message_bytes})
        return {"items": rows, "mailbox": self.mailbox, "uidvalidity": self.uidvalidity, "truncated": len(values) > len(selected), "next_after_uid": max(selected) if selected else after_uid, "read_only": True}

    def fetch(self, uids, destination, expected_uidvalidity, total_limit=64 * 1024 * 1024):
        if self.uidvalidity != expected_uidvalidity:
            raise AcquisitionError("UIDVALIDITY changed or differs from the authorized inventory; review the mailbox again.")
        if destination.exists():
            raise AcquisitionError("Acquisition destination must be a new directory.")
        destination.mkdir(parents=True)
        if os.name != "nt":
            destination.chmod(0o700)
        manifest = {"format": "casequarry-imap-acquisition-v1", "host": self.host, "port": self.port, "account": self.username, "mailbox": self.mailbox, "uidvalidity": self.uidvalidity, "read_only": True, "items": []}
        total = 0
        try:
            for uid in uids:
                self.connection.byte_budget = 32 * 1024
                status, meta = self.connection.uid("FETCH", str(uid), "(UID RFC822.SIZE)")
                raw = b" ".join(value for value in meta if isinstance(value, bytes))
                size = re.search(rb"RFC822.SIZE\s+(\d+)", raw, re.IGNORECASE)
                returned_uids = set(re.findall(rb"\bUID\s+(\d+)", raw, re.IGNORECASE))
                if status != "OK" or not size or returned_uids != {str(uid).encode()} or int(size[1]) > self.max_message_bytes or total + int(size[1]) > total_limit:
                    raise AcquisitionError("Message is unavailable or exceeds acquisition byte limits.")
                self.connection.byte_budget = self.max_message_bytes + 32 * 1024
                status, response = self.connection.uid("FETCH", str(uid), "(UID BODY.PEEK[])")
                bodies = [item[1] for item in response if isinstance(item, tuple) and isinstance(item[1], bytes)]
                header = b" ".join(item[0] if isinstance(item, tuple) else item for item in response if isinstance(item, (tuple, bytes)))
                returned_uids = set(re.findall(rb"\bUID\s+(\d+)", header, re.IGNORECASE))
                if status != "OK" or len(bodies) != 1 or len(bodies[0]) != int(size[1]) or returned_uids != {str(uid).encode()}:
                    raise AcquisitionError("Returned original literal differs from the inventoried size.")
                content = bodies[0]
                total += len(content)
                name = f"uid-{uid}.eml"
                (destination / name).write_bytes(content)
                if os.name != "nt":
                    (destination / name).chmod(0o600)
                source_host = f"[{self.host}]" if ":" in self.host else self.host
                manifest["items"].append({"uid": uid, "filename": name, "byte_size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "original_path": f"imap://{source_host}:{self.port}/{quote(self.username, safe='')}/{quote(self.mailbox, safe='')}/{self.uidvalidity}/{uid}"})
                (destination / "acquisition-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            manifest["state"] = "completed"
            return manifest
        finally:
            manifest.setdefault("state", "partial")
            (destination / "acquisition-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def safe_failure(error):
    if isinstance(error, AcquisitionError):
        fail(str(error), 2)
    if isinstance(error, (ssl.SSLError, OSError, imaplib.IMAP4.error)):
        fail("Secure mailbox acquisition failed. Check TLS, explicit scope and credentials; no remote writes were requested.", 7)
    raise error
