"""Isolated, fixed-command renderer/OCR worker with per-page process timeout."""

import csv
import json
import math
import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path


def run(job):
    from PIL import Image

    directory = Path(job["result"]).parent
    raster = directory / "page.png"
    metadata = {"engine": "tesseract", "language": job["language"], "quality": "needs-human-verification"}
    if job["page"] is not None:
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(job["path"]) as document:
            with closing(document[job["page"]]) as page:
                width, height = page.get_size()
                if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                    return {"text": "", "error": "OCR_DIMENSIONS_INVALID"}
                scale = min(job["dpi"] / 72, math.sqrt(job["max_pixels"] / (width * height)) * 0.99)
                if scale <= 0 or width * scale > 30_000 or height * scale > 30_000:
                    return {"text": "", "error": "OCR_PIXEL_LIMIT"}
                with closing(page.render(scale=scale)) as bitmap:
                    image = bitmap.to_pil()
                    try:
                        image.save(raster)
                    finally:
                        image.close()
                metadata["render_dpi"] = round(scale * 72, 2)
    else:
        with Image.open(job["path"]) as image:
            if image.width * image.height > job["max_pixels"]:
                return {"text": "", "error": "OCR_PIXEL_LIMIT"}
            if getattr(image, "n_frames", 1) > 1:
                metadata["warning"] = "Only the first image frame was recognized."
            image.convert("RGB").save(raster)
    output = directory / "recognition"
    process = subprocess.run(
        [job["engine"], str(raster), str(output), "-l", job["language"], "--dpi", str(job["dpi"]), "txt", "tsv"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=job["timeout"], check=False,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if process.returncode or not output.with_suffix(".txt").is_file():
        return {"text": "", "error": "OCR_FAILED"}
    with output.with_suffix(".txt").open("rb") as stream:
        raw = stream.read(job["max_chars"] * 4 + 1)
    text = raw.decode("utf-8", errors="replace")
    error = "TEXT_LIMIT" if len(text) > job["max_chars"] else None
    text = text[:job["max_chars"]]
    confidence = []
    tsv = output.with_suffix(".tsv")
    if tsv.is_file() and tsv.stat().st_size <= 16 * 1024 * 1024:
        with tsv.open(encoding="utf-8", errors="replace", newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream, delimiter="\t")):
                if index >= 250_000:
                    metadata["warning"] = "OCR confidence sample reached its row limit."
                    break
                try:
                    value = float(row.get("conf", "-1"))
                except ValueError:
                    continue
                if row.get("text", "").strip() and 0 <= value <= 100:
                    confidence.append(value)
    metadata.update(word_count=len(confidence), mean_confidence=round(sum(confidence) / len(confidence), 2) if confidence else None)
    if not text.strip():
        error = "OCR_NO_TEXT"
    if metadata.get("warning") and not error:
        error = "OCR_PARTIAL_FRAMES"
    return {"text": text, "error": error, **metadata}


def main():
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        result = run(job)
    except subprocess.TimeoutExpired:
        result = {"text": "", "error": "OCR_TIMEOUT"}
    except Exception as error:
        result = {"text": "", "error": "OCR_FAILED", "failure_type": type(error).__name__}
    Path(job["result"]).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
