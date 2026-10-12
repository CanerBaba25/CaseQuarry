"""Small deterministic, exclusively fictional evidence for security acceptance tests."""

import io
import stat
import zipfile
from email.message import EmailMessage
from email.policy import SMTP


def eml_bytes(
    sequence: int = 1,
    *,
    sender: str = "alice@example.test",
    recipient: str = "bob@example.test",
    subject: str = "Project Atlas payment approval",
    body: str = "Project Atlas invoice INV-2048 payment approved for USD 4,200.",
    attachment: bool = False,
    html: bool = False,
) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["From"] = f"Alice Example <{sender}>"
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = f"{sequence % 28 + 1:02d} Jan 2025 10:00:00 -0500"
    message["Message-ID"] = f"<synthetic-{sequence}@example.test>"
    if sequence > 1:
        message["In-Reply-To"] = "<synthetic-1@example.test>"
        message["References"] = "<synthetic-1@example.test>"
    message.set_content(body)
    if html:
        message.add_alternative(
            "<p>Project Atlas payment approved.</p>"
            "<script>window.__evidenceExecuted = true</script>"
            '<img src="https://tracking.example.test/pixel">'
            '<a href="javascript:alert(1)">Unsafe link</a>',
            subtype="html",
        )
    if attachment:
        message.add_attachment(
            b"Synthetic attachment: invoice INV-2048 approved.\n",
            maintype="text",
            subtype="plain",
            filename="invoice.txt",
        )
    return message.as_bytes()


def pdf_bytes() -> bytes:
    """Two-page uncompressed PDF; no document-generation dependency required."""
    streams = [
        b"BT /F1 12 Tf 50 750 Td (Project Atlas invoice approval, page one.) Tj ET",
        b"BT /F1 12 Tf 50 750 Td (Shipment delayed, page two.) Tj ET",
    ]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for stream in streams:
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def mbox_bytes() -> bytes:
    messages = [
        eml_bytes(10, body="Project Atlas first mailbox record.\nFrom synthetic body text is not a boundary."),
        eml_bytes(11, body="Project Atlas second mailbox record."),
    ]
    archive = bytearray()
    for raw in messages:
        archive.extend(b"From alice@example.test Thu Jan 02 15:00:00 2025\n")
        for line in raw.replace(b"\r\n", b"\n").splitlines(keepends=True):
            if line.startswith(b"From "):
                archive.extend(b">")
            archive.extend(line)
        archive.extend(b"\n")
    return bytes(archive)


def zip_bytes(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    destination = io.BytesIO()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        if symlink is not None:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../outside-target")
    return destination.getvalue()
