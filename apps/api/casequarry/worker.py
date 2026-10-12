import logging
import threading

from .ai_routes import process_pending_ai
from .config import Settings
from .database import Database
from .exports import process_pending_exports
from .ingestion import claim_import, run_batch
from .storage import Storage

LOGGER = logging.getLogger("casequarry.worker")


def worker_loop(database, settings, storage, stop_event):
    while not stop_event.is_set():
        try:
            batch_id = claim_import(database)
            if batch_id:
                run_batch(database, settings, storage, batch_id)
            process_pending_exports(database, settings, storage)
            process_pending_ai(database, settings, storage)
        except Exception as error:
            LOGGER.error("worker_tick_failed error_type=%s", type(error).__name__)
        stop_event.wait(settings.worker_poll_seconds)


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
