import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.database import SessionLocal
from app.parsers.registry import ParserRegistry
from app.core.config import settings
from app.services.adaptive_scheduler import AdaptiveScheduler, SchedulePlan
from app.services.parser_service import ParserService
from app.services.sync_service import SyncService


class ParserWorker:
    def __init__(self, interval_sec: int) -> None:
        self._interval_sec = interval_sec
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        logging.info("Parser worker starting: interval_sec=%s", self._interval_sec)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        registry = ParserRegistry()
        scheduler = AdaptiveScheduler(
            interval_sec=self._interval_sec,
            max_workers=settings.scheduler_max_workers,
            alpha=settings.scheduler_alpha,
        )
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            plan: SchedulePlan | None = None
            try:
                with SessionLocal() as db:
                    site_keys = registry.enabled_sites()
                    logging.info("Parser cycle: sites=%s", site_keys)
                    plan = scheduler.build_plan(db, site_keys)
                if plan.site_groups:
                    with ThreadPoolExecutor(max_workers=plan.required_workers) as executor:
                        futures = [
                            executor.submit(self._run_group, group)
                            for group in plan.site_groups
                            if group
                        ]
                        for future in futures:
                            try:
                                future.result()
                            except Exception:  # noqa: BLE001
                                logging.exception("Parser group failed")
                with SessionLocal() as db:
                    SyncService.send_pending_products(db)
                    SyncService.send_site_statuses(db)
            except Exception:  # noqa: BLE001
                logging.exception("Parser worker failed")
            cycle_elapsed = time.monotonic() - cycle_start
            self._log_cycle_metrics(plan, cycle_elapsed)
            remaining = self._interval_sec - cycle_elapsed
            if remaining > 0:
                self._stop_event.wait(remaining)
            else:
                logging.warning("Parser cycle overran: elapsed_sec=%.2f", cycle_elapsed)

    def _run_group(self, site_keys: list[str]) -> None:
        with SessionLocal() as db:
            for site_key in site_keys:
                if self._stop_event.is_set():
                    break
                try:
                    logging.info("Parser start: site_key=%s", site_key)
                    ParserService.parse_site(db, site_key)
                    logging.info("Parser done: site_key=%s", site_key)
                except Exception:  # noqa: BLE001
                    logging.exception("Parser failed: site_key=%s", site_key)

    @staticmethod
    def _log_cycle_metrics(plan: SchedulePlan | None, cycle_elapsed: float) -> None:
        if not plan or plan.required_workers <= 0:
            logging.info("Parser cycle metrics: elapsed_sec=%.2f", cycle_elapsed)
            return
        capacity = plan.required_workers * settings.sync_interval_sec
        utilization = 0.0
        if capacity > 0:
            utilization = (plan.total_expected_sec / capacity) * 100.0
        logging.info(
            "Parser cycle metrics: elapsed_sec=%.2f required_workers=%s utilization_pct=%.1f",
            cycle_elapsed,
            plan.required_workers,
            utilization,
        )
