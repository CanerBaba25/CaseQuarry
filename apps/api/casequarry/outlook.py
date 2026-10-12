"""Read a bounded MS-OXMSG subset without Outlook automation or external links."""

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import Parser
from email.utils import parsedate_to_datetime
from pathlib import Path

from .parsers import Parsed, addresses, safe_text_html


class MsgError(ValueError):
    pass


def decode_msg(path, filename, limits):
    import olefile

    if path.stat().st_size > limits["upload"]:
        raise MsgError("MSG_SIZE_LIMIT")
    if not olefile.isOleFile(path):
        raise MsgError("MIME_MISMATCH")
    with olefile.OleFileIO(path, raise_defects=olefile.DEFECT_INCORRECT) as ole:
        entries = ole.listdir(streams=True, storages=True)
        if len(entries) > limits["entries"]:
            raise MsgError("MSG_ENTRY_LIMIT")

        def read(name, prefix=(), maximum=None):
            key = [*prefix, name]
            if not ole.exists(key):
                return b""
            cap = min(maximum or limits["chars"] * 4 + 4, limits["upload"])
            if ole.get_size(key) > cap:
                raise MsgError("MSG_PROPERTY_LIMIT")
            with ole.openstream(key) as stream:
                return stream.read(cap + 1)

        def string(tag, prefix=()):
            value = read(f"__substg1.0_{tag:04X}001F", prefix)
            if value:
                return value.decode("utf-16-le", errors="replace").rstrip("\x00")
            value = read(f"__substg1.0_{tag:04X}001E", prefix)
            return value.decode("cp1252", errors="replace").rstrip("\x00")

        def fixed(prefix=(), header=32):
            raw = read("__properties_version1.0", prefix)
            return {struct.unpack_from("<I", raw, offset)[0]: raw[offset + 8:offset + 16] for offset in range(header, len(raw) - 15, 16)}

        properties = fixed()
        message_class = string(0x001A)
        if not message_class.startswith("IPM.Note"):
            return Parsed("file", filename, state="unsupported", error="MSG_CLASS_UNSUPPORTED", metadata={"format": "msg", "message_class": message_class})
        if "SMIME" in message_class.upper() or "RPMSG" in message_class.upper():
            return Parsed("email", filename, state="locked", error="MSG_ENCRYPTED", metadata={"format": "msg", "message_class": message_class})
        header = string(0x007D)
        message = Parser(policy=policy.default).parsestr(header + "\n\n", headersonly=True)
        result = Parsed("email", string(0x0037) or filename, metadata={"format": "msg", "parser": "casequarry-ms-oxmsg-subset", "message_class": message_class, "extraction_method": "mapi-properties"})
        result.email = {role: addresses(str(message.get(field, ""))) for role, field in [("from", "From"), ("to", "To"), ("cc", "Cc"), ("bcc", "Bcc"), ("reply_to", "Reply-To")]}
        result.email.update(raw_headers=header, message_id=string(0x1035) or str(message.get("Message-ID", "")), in_reply_to=string(0x1042) or str(message.get("In-Reply-To", "")), references=re.findall(r"<[^>]+>", str(message.get("References", ""))))
        if not result.email["from"]:
            address = string(0x5D01) or string(0x0C1F)
            if address:
                result.email["from"] = [{"name": string(0x0C1A), "email": address.lower()}]
        storages = sorted({entry[0] for entry in entries if entry[0].startswith("__recip_version1.0_#")})
        if len(storages) > 1000:
            raise MsgError("MSG_RECIPIENT_LIMIT")
        recipients = {"to": [], "cc": [], "bcc": []}
        for storage in storages:
            props = fixed((storage,), 8)
            kind = struct.unpack("<I", props.get(0x0C150003, b"\x01\0\0\0\0\0\0\0")[:4])[0]
            email = string(0x39FE, (storage,)) or string(0x3003, (storage,))
            if email:
                recipients[{1: "to", 2: "cc", 3: "bcc"}.get(kind, "to")].append({"name": string(0x3001, (storage,)), "email": email.lower()})
        for role, values in recipients.items():
            if values:
                result.email[role] = values
        result.sender = ", ".join(value["email"] for value in result.email["from"])
        result.recipients = ", ".join(value["email"] for role in ("to", "cc", "bcc") for value in result.email[role])
        sent = properties.get(0x00390040)
        if sent:
            ticks = struct.unpack("<Q", sent)[0]
            result.date_utc = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10)
            result.date_raw, result.timezone_source = str(ticks), "mapi-filetime-utc"
        elif message.get("Date"):
            result.date_raw = str(message.get("Date"))
            try:
                date = parsedate_to_datetime(result.date_raw)
                if date.tzinfo:
                    result.date_utc, result.timezone_source = date.astimezone(UTC), "explicit"
                else:
                    result.timezone_source = "unknown"
            except (TypeError, ValueError, OverflowError):
                result.metadata["date_warning"] = "The original transport date could not be normalized."
        result.email["sent_at_raw"] = result.date_raw
        result.text = string(0x1000)
        if not result.text:
            html = read("__substg1.0_10130102")
            if html:
                result.text = safe_text_html(html.decode("utf-8", errors="replace"))
        if not result.text:
            result.state, result.error = "partial", "MSG_BODY_UNSUPPORTED" if read("__substg1.0_10090102") else "NO_EXTRACTED_TEXT"
        attachment_names = sorted({entry[0] for entry in entries if entry[0].startswith("__attach_version1.0_#")})
        if len(attachment_names) > 200:
            raise MsgError("ATTACHMENT_LIMIT")
        total = 0
        for index, storage in enumerate(attachment_names):
            prefix = (storage,)
            if ole.exists([storage, "__substg1.0_3701000D"]):
                result.state, result.error = "partial", "MSG_EMBEDDED_MESSAGE_UNSUPPORTED"
                continue
            key = "__substg1.0_37010102"
            if not ole.exists([storage, key]):
                result.state, result.error = "partial", "MSG_ATTACHMENT_UNSUPPORTED"
                continue
            size = ole.get_size([storage, key])
            total += size
            if total > limits["attachments"]:
                result.state, result.error = "partial", "ATTACHMENT_SIZE_LIMIT"
                break
            data = read(key, prefix, limits["attachments"])
            name = string(0x3707, prefix) or string(0x3704, prefix) or f"attachment-{index + 1}"
            result.attachments.append((Path(name.replace("\\", "/")).name[:400], data))
        if len(result.text) > limits["chars"]:
            result.text, result.state, result.error = result.text[:limits["chars"]], "partial", "TEXT_LIMIT"
        if "\ufffd" in result.text:
            result.state, result.error = "partial", "ENCODING_REPLACEMENTS"
        if any(entry[-1].endswith("001E") for entry in entries):
            result.metadata["encoding_warning"] = "String8 properties use a Windows-1252 fallback; verify non-ASCII characters against the original."
        if ole.parsing_issues:
            result.metadata["ole_warnings"] = [str(value[1])[:200] for value in ole.parsing_issues[:20]]
        result.metadata["unsupported_features"] = ["compressed-rtf-only bodies", "embedded MSG attachments", "external/OLE attachments", "appointments and contacts", "encrypted messages"]
        return result


def parse_msg(path, filename, settings):
    with tempfile.TemporaryDirectory(prefix="casequarry-msg-") as directory:
        root = Path(directory)
        job = root / "job.json"
        job.write_text(json.dumps({"path": str(path.resolve()), "filename": filename, "root": str(root), "limits": {"upload": settings.max_upload_bytes, "chars": settings.max_extracted_chars, "entries": settings.max_archive_entries, "attachments": min(settings.max_archive_expanded_bytes, 64 * 1024 * 1024)}}), encoding="utf-8")
        try:
            process = subprocess.run([sys.executable, "-m", "casequarry.outlook_worker", str(job)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if process.returncode:
                return Parsed("email", filename, state="failed", error="MSG_PARSE_FAILED")
            with (root / "result.json").open("rb") as stream:
                raw = stream.read(settings.max_extracted_chars * 6 + 2_000_000)
                if stream.read(1):
                    raise MsgError("MSG_OUTPUT_LIMIT")
            data = json.loads(raw)
            attachments = data.pop("attachments", [])
            if data.get("date_utc"):
                data["date_utc"] = datetime.fromisoformat(data["date_utc"])
            result = Parsed(**data)
            total = 0
            for index, item in enumerate(attachments):
                # Only fixed worker-generated filenames are read, never source-supplied paths.
                child = root / f"attachment-{index}.bin"
                total += child.stat().st_size
                if total > 64 * 1024 * 1024:
                    raise MsgError("ATTACHMENT_SIZE_LIMIT")
                result.attachments.append((item, child.read_bytes()))
            return result
        except subprocess.TimeoutExpired:
            return Parsed("email", filename, state="partial", error="MSG_TIMEOUT")
        except (OSError, ValueError, TypeError):
            return Parsed("email", filename, state="failed", error="MSG_PARSE_FAILED")
