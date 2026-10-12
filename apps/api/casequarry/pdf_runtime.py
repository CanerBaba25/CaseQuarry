"""PDFium has process-global state: serialize every in-process call."""

from threading import RLock

PDFIUM_LOCK = RLock()
