import logging
import threading

from app.core.database import SessionLocal
from app.parsers.registry import ParserRegistry
from app.services.parser_service import ParserService
from app.services.sync_service import SyncService


class ParserWorker:
    def __init__(self, interval_sec: int) -> None:
        self._interval_sec = interval_sec
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        registry = ParserRegistry()
        while not self._stop_event.is_set():
            try:
                with SessionLocal() as db:
                    for site_key in registry.enabled_sites():
                        try:
                            ParserService.parse_site(db, site_key)
                        except Exception:  # noqa: BLE001
                            logging.exception("Parser failed", extra={"site_key": site_key})
                    SyncService.send_pending_products(db)
                    SyncService.send_site_statuses(db)
            except Exception:  # noqa: BLE001
                logging.exception("Parser worker failed")
            self._stop_event.wait(self._interval_sec)
