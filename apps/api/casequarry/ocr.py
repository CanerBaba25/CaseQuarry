"""Bounded local OCR orchestration; originals are never handed to an editor."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path


def tesseract_path(settings):
    configured = settings.tesseract_command
    if configured:
        resolved = shutil.which(configured)
        return resolved if resolved and Path(resolved).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    if os.name == "nt":
        candidates = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR/tesseract.exe"]
        if os.environ.get("LOCALAPPDATA"):
            candidates.append(Path(os.environ["LOCALAPPDATA"]) / "CaseQuarryTools/tesseract/tesseract.exe")
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def availability(settings, *, pdf=False):
    if not settings.ocr_enabled:
        return "disabled", "Local OCR is disabled by the administrator."
    if not re.fullmatch(r"[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*", settings.ocr_language):
        return "dependency_missing", "Configure a valid installed Tesseract language identifier."
    engine = tesseract_path(settings)
    if not engine:
        return "dependency_missing", "Install local Tesseract and the requested language data."
    languages = installed_languages(engine, int(time.monotonic() // 60))
    if not set(settings.ocr_language.split("+")).issubset(languages):
        return "dependency_missing", "The requested Tesseract language data is unavailable; install it locally."
    if pdf and importlib.util.find_spec("pypdfium2") is None:
        return "dependency_missing", "Install the pypdfium2 PDF renderer."
    return "available", "Local Tesseract OCR; recognition requires human verification."


@lru_cache(maxsize=16)
def installed_languages(engine, cache_minute):
    del cache_minute
    try:
        with tempfile.TemporaryFile() as output:
            process = subprocess.run([engine, "--list-langs"], stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, timeout=5, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            output.seek(0)
            raw = output.read(32_769)
        if process.returncode or len(raw) > 32_768:
            return frozenset()
        return frozenset(line.strip() for line in raw.decode("utf-8", errors="replace").splitlines() if re.fullmatch(r"[A-Za-z0-9_]+", line.strip()))
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()


def recognize(path, settings, *, page=None):
    status, detail = availability(settings, pdf=page is not None)
    if status != "available":
        return {"text": "", "error": "OCR_DISABLED" if status == "disabled" else "OCR_DEPENDENCY_MISSING", "detail": detail}
    with tempfile.TemporaryDirectory(prefix="casequarry-ocr-") as directory:
        job = Path(directory) / "job.json"
        result = Path(directory) / "result.json"
        job.write_text(json.dumps({
            "path": str(path.resolve()), "page": page, "result": str(result),
            "engine": tesseract_path(settings), "language": settings.ocr_language,
            "timeout": settings.ocr_timeout_seconds, "max_pixels": settings.ocr_max_pixels,
            "dpi": settings.ocr_dpi, "max_chars": settings.max_extracted_chars,
        }), encoding="utf-8")
        try:
            process = subprocess.run(
                [sys.executable, "-m", "casequarry.ocr_worker", str(job)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=settings.ocr_timeout_seconds + 15, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if process.returncode or not result.is_file():
                return {"text": "", "error": "OCR_FAILED"}
            with result.open("rb") as stream:
                data = stream.read(settings.max_extracted_chars * 6 + 16_384)
                if stream.read(1):
                    return {"text": "", "error": "OCR_OUTPUT_LIMIT"}
            return json.loads(data)
        except subprocess.TimeoutExpired:
            return {"text": "", "error": "OCR_TIMEOUT"}
        except (OSError, ValueError):
            return {"text": "", "error": "OCR_FAILED"}
