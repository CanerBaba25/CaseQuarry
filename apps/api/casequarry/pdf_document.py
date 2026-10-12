"""Isolated native PDF text extraction and per-page local OCR fallback."""

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from .parsers import Parsed

FIELDS = ("max_extracted_chars", "ocr_enabled", "ocr_language", "ocr_timeout_seconds", "ocr_max_pages", "ocr_max_pixels", "ocr_dpi", "tesseract_command", "extraction_timeout_seconds")


def extract(path, filename, settings):
    from pypdf import PdfReader

    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            return Parsed("pdf", filename, state="failed", error="MIME_MISMATCH")
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        return Parsed("pdf", filename, state="locked", error="PASSWORD_REQUIRED")
    result = Parsed("pdf", filename, metadata={"page_count": len(reader.pages)})
    parts, offset, page_methods = [], 0, []
    deadline = time.monotonic() + settings.extraction_timeout_seconds
    for number in range(min(len(reader.pages), settings.ocr_max_pages)):
        if time.monotonic() >= deadline:
            result.state, result.error = "partial", "EXTRACTION_TIME_LIMIT"
            break
        text = reader.pages[number].extract_text() or ""
        method = {"page": number + 1, "method": "pdf-text"}
        if not text.strip():
            from .ocr import recognize
            recognized = recognize(path, settings, page=number)
            text = recognized.pop("text", "")
            method.update(method="ocr", **recognized)
            if recognized.get("error"):
                result.state, result.error = "partial", recognized["error"]
        page_methods.append(method)
        if offset + len(text) > settings.max_extracted_chars:
            result.state, result.error = "partial", "TEXT_LIMIT"
            break
        result.pages.append((number + 1, offset, offset + len(text)))
        parts.append(text)
        offset += len(text) + 2
    result.text = "\n\n".join(parts)
    has_ocr = any(item["method"] == "ocr" for item in page_methods)
    result.metadata.update(extraction_method="pdf-text+local-ocr" if has_ocr else "pdf-text", ocr_pages=page_methods)
    if len(reader.pages) > settings.ocr_max_pages:
        result.state, result.error = "partial", "PDF_PAGE_LIMIT"
    if has_ocr:
        result.metadata.update(ocr_engine="tesseract", ocr_language=settings.ocr_language, ocr_quality="needs-human-verification")
    return result


def parse_pdf(path, filename, settings):
    with tempfile.TemporaryDirectory(prefix="casequarry-pdf-") as directory:
        root = Path(directory)
        job = root / "job.json"
        job.write_text(json.dumps({"path": str(path.resolve()), "filename": filename, "settings": {key: getattr(settings, key) for key in FIELDS}, "result": str(root / "result.json")}), encoding="utf-8")
        try:
            process = subprocess.run([sys.executable, "-m", "casequarry.pdf_document", str(job)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=settings.extraction_timeout_seconds + settings.ocr_timeout_seconds + 20, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if process.returncode:
                return Parsed("pdf", filename, state="failed", error="PDF_WORKER_FAILED")
            with (root / "result.json").open("rb") as stream:
                data = stream.read(settings.max_extracted_chars * 6 + settings.ocr_max_pages * 2048 + 16_384)
                if stream.read(1):
                    return Parsed("pdf", filename, state="partial", error="PDF_OUTPUT_LIMIT")
            value = json.loads(data)
            value["pages"] = [tuple(item) for item in value.get("pages", [])]
            return Parsed(**value)
        except subprocess.TimeoutExpired:
            return Parsed("pdf", filename, state="partial", error="EXTRACTION_TIME_LIMIT")
        except (OSError, ValueError, TypeError):
            return Parsed("pdf", filename, state="failed", error="PDF_WORKER_FAILED")


def main():
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        result = extract(Path(job["path"]), job["filename"], SimpleNamespace(**job["settings"]))
    except Exception as error:
        result = Parsed("pdf", job["filename"], state="failed", error=f"PARSE_FAILED:{type(error).__name__}")
    Path(job["result"]).write_text(json.dumps(asdict(result)), encoding="utf-8")


if __name__ == "__main__":
    main()
