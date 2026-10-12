import logging
import threading

from .ai_routes import process_pending_ai
from .config import Settings
from .database import Database
from .exports import process_pending_exports
from .ingestion import claim_import, run_batch
from .production_routes import process_pending_productions
from .storage import Storage

LOGGER = logging.getLogger("casequarry.worker")


def worker_loop(database, settings, storage, stop_event):
    active_import = None
    while not stop_event.is_set():
        try:
            if active_import is None or not active_import.is_alive():
                batch_id = claim_import(database, remember=False)
                if batch_id:
                    active_import = threading.Thread(target=run_batch, args=(database, settings, storage, batch_id), kwargs={"max_records": settings.worker_import_records_per_tick, "stop_event": stop_event}, name="casequarry-import-slot", daemon=True)
                    active_import.start()
            process_pending_exports(database, settings, storage)
            process_pending_productions(database, settings, storage)
            process_pending_ai(database, settings, storage)
        except Exception as error:
            LOGGER.error("worker_tick_failed error_type=%s", type(error).__name__)
        stop_event.wait(settings.worker_poll_seconds)
    if active_import is not None:
        active_import.join(timeout=2)


def main():
    import signal

    settings = Settings(worker_mode="external")
    database, storage = Database(settings), Storage(settings.storage_path)
    database.initialize()
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    try:
        worker_loop(database, settings, storage, stop_event)
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
