from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Callable
from uuid import uuid4

from app.schemas.run_report import SourceRunReport
from app.schemas.sync_stages import STAGE_LABEL_RU, SyncStageCode
from app.services.run_logger import subscribe_run_events, unsubscribe_run_events


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@dataclass(slots=True)
class RuntimeEvent:
    event_id: str
    job_id: str
    seq_no: int
    type: str
    ts: datetime
    payload: dict


@dataclass(slots=True)
class RuntimeJob:
    job_id: str
    status: str
    created_at: datetime
    dry_run: bool
    source_keys: list[str] = field(default_factory=list)
    source_candidate_urls: dict[str, list[str]] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_source_name: str | None = None
    current_source_index: int = 0
    current_strategy: str | None = None
    current_stage: str | None = None
    products_success: int = 0
    products_error: int = 0
    error: str | None = None
    cancel_requested: bool = False
    seq_counter: int = 0
    events: list[RuntimeEvent] = field(default_factory=list)
    processed_sources: int = 0
    current_progress_percent: float = 0.0


class SyncOrchestratorService:
    def __init__(self, max_workers: int = 1) -> None:
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, RuntimeJob] = {}
        self._active_job_id: str | None = None
        self._latest_job_id: str | None = None

    def create_job(
        self,
        *,
        source_keys: list[str],
        source_candidate_urls: dict[str, list[str]] | None = None,
        dry_run: bool,
        runner: Callable[[str, bool, str, list[str]], SourceRunReport],
    ) -> RuntimeJob:
        with self._lock:
            if self._active_job_id:
                active = self._jobs.get(self._active_job_id)
                if active and active.status in {"queued", "in_progress"}:
                    raise RuntimeError("sync already in progress")
            job = RuntimeJob(
                job_id=str(uuid4()),
                status="queued",
                created_at=_utcnow(),
                dry_run=dry_run,
                source_keys=list(source_keys),
                source_candidate_urls=dict(source_candidate_urls or {}),
            )
            self._jobs[job.job_id] = job
            self._active_job_id = job.job_id
            self._latest_job_id = job.job_id
        self._executor.submit(self._execute, job.job_id, runner)
        return job

    def get_job(self, job_id: str) -> RuntimeJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_latest(self) -> RuntimeJob | None:
        with self._lock:
            if not self._latest_job_id:
                return None
            return self._jobs.get(self._latest_job_id)

    def cancel(self, job_id: str) -> RuntimeJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status in {"completed", "failed", "cancelled"}:
                return job
            job.cancel_requested = True
            # Release active slot immediately even for in-progress job:
            # long-running source execution can ignore cancel_requested for a while,
            # and we must not block all next probe/manual launches with 409.
            if job.status in {"queued", "in_progress"}:
                job.status = "cancelled"
                job.finished_at = _utcnow()
                if self._active_job_id == job.job_id:
                    self._active_job_id = None
                self._append_event(job, "job_cancelled", {"reason": "cancel_requested_immediate"})
            return job

    def get_events(self, job_id: str, cursor: int, limit: int) -> tuple[list[RuntimeEvent], int]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return ([], cursor)
            items = [evt for evt in job.events if evt.seq_no > cursor][: max(1, limit)]
            next_cursor = cursor
            if items:
                next_cursor = items[-1].seq_no
            return (items, next_cursor)

    def _append_event(self, job: RuntimeJob, event_type: str, payload: dict) -> None:
        job.seq_counter += 1
        job.events.append(
            RuntimeEvent(
                event_id=f"evt_{job.job_id}_{job.seq_counter}",
                job_id=job.job_id,
                seq_no=job.seq_counter,
                type=event_type,
                ts=_utcnow(),
                payload=dict(payload or {}),
            )
        )

    @staticmethod
    def _stage_label(stage_code: SyncStageCode) -> str:
        return STAGE_LABEL_RU.get(stage_code, "Выполнение")

    @staticmethod
    def _raw_strategy_stage_to_contract(strategy: str | None, stage: str | None) -> tuple[SyncStageCode, str]:
        strategy_name = str(strategy or "").strip()
        stage_name = str(stage or "").strip()
        if stage_name == "discover_start":
            return (SyncStageCode.DISCOVER_PRODUCTS, STAGE_LABEL_RU[SyncStageCode.DISCOVER_PRODUCTS])
        if stage_name == "discover_done":
            return (SyncStageCode.DISCOVER_DONE, STAGE_LABEL_RU[SyncStageCode.DISCOVER_DONE])
        if stage_name == "fetch_start":
            return (SyncStageCode.FETCH_START, STAGE_LABEL_RU[SyncStageCode.FETCH_START])
        if stage_name == "fetch_progress":
            return (SyncStageCode.FETCH_PROGRESS, STAGE_LABEL_RU[SyncStageCode.FETCH_PROGRESS])
        if stage_name == "fetch_skip":
            return (SyncStageCode.FETCH_SKIP, STAGE_LABEL_RU[SyncStageCode.FETCH_SKIP])
        if stage_name in {"run_done", "done"}:
            return (SyncStageCode.SOURCE_DONE, STAGE_LABEL_RU[SyncStageCode.SOURCE_DONE])
        if stage_name.startswith("live_dom"):
            return (SyncStageCode.DISCOVER_PRODUCTS, "Сканирование витрины (DOM)")
        if stage_name.startswith("export progress"):
            return (SyncStageCode.EXPORT_PRODUCTS, "Экспорт карточек товаров")
        if stage_name.startswith("export done"):
            return (SyncStageCode.EXPORT_PRODUCTS, "Экспорт карточек товаров")
        if stage_name.startswith("export"):
            return (SyncStageCode.EXPORT_PRODUCTS, STAGE_LABEL_RU[SyncStageCode.EXPORT_PRODUCTS])
        if stage_name.startswith("sitemap "):
            return (SyncStageCode.DISCOVER_PRODUCTS, "Сбор ссылок товаров")
        if stage_name.startswith("products.js progress"):
            return (SyncStageCode.DISCOVER_PRODUCTS, "Проверка доступа к карточкам")
        if stage_name.startswith("phase="):
            return (SyncStageCode.STRATEGY_RUN, "Выполнение сценария браузера")
        if strategy_name == "shopify_browser_extension" and stage_name:
            return (SyncStageCode.STRATEGY_RUN, "Выполнение браузерного сценария")
        return (SyncStageCode.STRATEGY_RUN, stage_name or STAGE_LABEL_RU[SyncStageCode.STRATEGY_RUN])

    @staticmethod
    def _to_float(value: object) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: object) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_product_batch_item(item: dict, *, source_key: str) -> dict:
        url = str(item.get("url") or "").strip()
        handle = str(item.get("handle") or "").strip()
        external_id = str(item.get("external_id") or "").strip() or None
        canonical_url = str(item.get("canonical_url") or "").strip() or url or None
        title = str(item.get("title") or "").strip() or None
        description = str(item.get("description") or "").strip() or None
        vendor = str(item.get("vendor") or item.get("brand") or "").strip() or None
        product_type = str(item.get("product_type") or item.get("category") or "").strip() or None
        item_currency = str(item.get("currency") or "").strip().upper() or None
        price = SyncOrchestratorService._to_float(item.get("price"))
        weight_grams = SyncOrchestratorService._to_int(item.get("weight_grams"))
        status = str(item.get("status") or "").strip().lower() or "unavailable"
        unavailable_reason = str(item.get("unavailable_reason") or "").strip() or None

        images_raw = item.get("images") if isinstance(item.get("images"), list) else []
        images: list[str] = []
        primary_image_url = str(item.get("image_url") or "").strip()
        if primary_image_url:
            images.append(primary_image_url)
        for image in images_raw:
            image_url = ""
            if isinstance(image, dict):
                image_url = str(image.get("src") or image.get("url") or "").strip()
            else:
                image_url = str(image or "").strip()
            if image_url:
                images.append(image_url)
        dedup_images: list[str] = []
        seen_images: set[str] = set()
        for image_url in images:
            if image_url in seen_images:
                continue
            seen_images.add(image_url)
            dedup_images.append(image_url)

        variants_raw = item.get("variants") if isinstance(item.get("variants"), list) else []
        variants: list[dict] = []
        for variant in variants_raw:
            if not isinstance(variant, dict):
                continue
            v_price = SyncOrchestratorService._to_float(variant.get("price"))
            source_variant_id = str(variant.get("id") or "").strip() or None
            source_variant_title = str(variant.get("title") or "").strip() or None
            variants.append(
                {
                    "id": source_variant_id,
                    "title": source_variant_title,
                    "sku": str(variant.get("sku") or "").strip() or None,
                    "price": v_price,
                    "currency": str(variant.get("currency") or item_currency or "").strip().upper() or None,
                    "available": bool(variant.get("available", True)),
                    # Variant-level source lineage: required for safe cross-source combine/merge.
                    "source_key": source_key,
                    "source_product_url": url or None,
                    "source_variant_id": source_variant_id,
                    "source_variant_title": source_variant_title,
                }
            )
        available_variants = [v for v in variants if bool(v.get("available", False))]
        if variants and status == "available" and not available_variants:
            status = "out_of_stock"
        elif variants and status == "out_of_stock" and available_variants:
            status = "available"

        return {
            "source_key": source_key,
            "source_product_url": url or None,
            "canonical_url": canonical_url,
            "external_id": external_id,
            "handle": handle or None,
            "title": title,
            "description": description,
            "vendor": vendor,
            "product_type": product_type,
            "price": price,
            "weight_grams": weight_grams,
            "status": status,
            "unavailable_reason": unavailable_reason,
            "images": dedup_images,
            "buyer_total_price": SyncOrchestratorService._to_float(item.get("buyer_total_price")),
            "buyer_service_fee": SyncOrchestratorService._to_float(item.get("buyer_service_fee")),
            "variants": variants,
        }

    def _build_product_batch_items(self, *, source_key: str, valid_products: list[dict], unavailable_products: list[dict]) -> list[dict]:
        out: list[dict] = []
        for raw in valid_products:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.setdefault("status", "available")
            normalized = self._normalize_product_batch_item(item, source_key=source_key)
            if not normalized.get("source_product_url"):
                continue
            if not isinstance(normalized.get("variants"), list) or not normalized.get("variants"):
                continue
            out.append(normalized)
        for raw in unavailable_products:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.setdefault("status", "unavailable")
            reasons_list = item.get("unavailable_reasons") if isinstance(item.get("unavailable_reasons"), list) else []
            normalized_reasons = [str(x).strip().lower() for x in reasons_list if str(x).strip()]
            reason_text = str(item.get("unavailable_reason") or "").strip().lower()
            # Business rule: only missing_weight-only unavailable products may reach backend.
            # Any missing_currency (or any other unavailable reason) must be dropped.
            allow_unavailable = False
            if normalized_reasons:
                unique_reasons = {x for x in normalized_reasons}
                allow_unavailable = unique_reasons == {"missing_weight"}
            elif reason_text:
                allow_unavailable = ("missing_weight" in reason_text) and ("missing_currency" not in reason_text)
            if not allow_unavailable:
                continue
            normalized = self._normalize_product_batch_item(item, source_key=source_key)
            if not normalized.get("source_product_url"):
                continue
            if not isinstance(normalized.get("variants"), list) or not normalized.get("variants"):
                continue
            out.append(normalized)
        return out

    def _execute(self, job_id: str, runner: Callable[[str, bool, str, list[str]], SourceRunReport]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = _utcnow()
                if self._active_job_id == job.job_id:
                    self._active_job_id = None
                self._append_event(job, "job_cancelled", {"reason": "cancelled_before_start"})
                return
            job.status = "in_progress"
            job.started_at = _utcnow()
            self._append_event(job, "job_started", {"total_sources": len(job.source_keys)})

        failed_sources = 0
        for index, source_key in enumerate(job.source_keys, start=1):
            with self._lock:
                job = self._jobs[job_id]
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.finished_at = _utcnow()
                    self._append_event(job, "job_cancelled", {"reason": "cancel_requested"})
                    if self._active_job_id == job.job_id:
                        self._active_job_id = None
                    return
                job.current_source_name = source_key
                job.current_source_index = index
                job.current_stage = "source_started"
                progress_percent = 0.0
                total = max(1, len(job.source_keys))
                if total > 0:
                    progress_percent = ((max(job.processed_sources, 0)) / total) * 100.0
                self._append_event(
                    job,
                    "source_started",
                    {
                        "source_key": source_key,
                        "source_index": index,
                        "total_sources": len(job.source_keys),
                        "stage_code": SyncStageCode.SOURCE_PREPARE.value,
                        "stage_label": self._stage_label(SyncStageCode.SOURCE_PREPARE),
                        "progress_percent": round(max(job.current_progress_percent, progress_percent), 2),
                    },
                )

            progress_run_id = f"sync:{job.job_id}:{source_key}:{index}"
            candidate_urls = list(job.source_candidate_urls.get(source_key, []))

            def _on_strategy_progress(event_payload: dict) -> None:
                event_type = str(event_payload.get("type") or "").strip()
                if event_type != "progress":
                    return
                strategy = str(event_payload.get("strategy") or "").strip()
                fields = event_payload.get("fields") if isinstance(event_payload.get("fields"), dict) else {}
                raw_stage = str(fields.get("stage") or "").strip() or "progress"
                stage_code, stage_label = self._raw_strategy_stage_to_contract(strategy=strategy, stage=raw_stage)
                strategy_percent: float | None = None
                pct_value = self._to_float(fields.get("pct"))
                if pct_value is None:
                    pct_value = self._to_float(fields.get("percent"))
                if pct_value is not None:
                    strategy_percent = max(0.0, min(100.0, pct_value))
                if strategy_percent is None:
                    processed_text = str(fields.get("processed") or "").strip()
                    if "/" in processed_text:
                        try:
                            left, right = processed_text.split("/", 1)
                            done = float(left.strip())
                            total_items = float(right.strip())
                            if total_items > 0:
                                strategy_percent = max(0.0, min(100.0, (done / total_items) * 100.0))
                        except Exception:
                            strategy_percent = None
                with self._lock:
                    live_job = self._jobs.get(job_id)
                    if not live_job or live_job.status not in {"in_progress", "queued"}:
                        return
                    live_job.current_strategy = strategy or live_job.current_strategy
                    stage_text = stage_label
                    total = max(1, len(live_job.source_keys))
                    source_completed_base = ((max(index - 1, 0)) / total) * 100.0
                    source_share = 100.0 / total
                    stage_share = (strategy_percent or 0.0) / 100.0
                    progress_percent = source_completed_base + (source_share * stage_share)
                    progress_percent = max(0.0, min(100.0, progress_percent))
                    # Global progress must be monotonic for UI: strategy internal stage
                    # can reset (for example second pass), but overall job progress must not decrease.
                    progress_percent = max(float(live_job.current_progress_percent or 0.0), progress_percent)
                    if strategy_percent is not None:
                        stage_text = f"{stage_text} | {int(round(strategy_percent))}%"
                    live_job.current_stage = stage_text
                    live_job.current_progress_percent = progress_percent
                    self._append_event(
                        live_job,
                        "source_progress",
                        {
                            "source_key": source_key,
                            "source_index": index,
                            "total_sources": len(live_job.source_keys),
                            "strategy": strategy,
                            "stage": raw_stage,
                            "stage_code": stage_code.value,
                            "stage_label": stage_label,
                            "products_success": live_job.products_success,
                            "products_error": live_job.products_error,
                            "fields": fields,
                            "progress_percent": round(progress_percent, 2),
                        },
                    )

            subscribe_run_events(progress_run_id, _on_strategy_progress)
            try:
                report = runner(source_key, job.dry_run, progress_run_id, candidate_urls)
                valid_products = list(report.valid_products or [])
                unavailable_products = list(report.unavailable_products or [])
                all_products = self._build_product_batch_items(
                    source_key=source_key,
                    valid_products=valid_products,
                    unavailable_products=unavailable_products,
                )
                strategy = None
                stage = "source_done"
                if report.attempts:
                    strategy = report.attempts[-1].strategy
                if str(report.status.value).lower() == "failed":
                    stage = "failed"
                stage_code = SyncStageCode.SOURCE_DONE if stage == "source_done" else SyncStageCode.SOURCE_FAILED
                with self._lock:
                    job = self._jobs[job_id]
                    job.current_strategy = strategy
                    job.current_stage = stage
                    completed_sources_progress = max(0.0, min(100.0, (index / max(1, len(job.source_keys))) * 100.0))
                    job.current_progress_percent = max(float(job.current_progress_percent or 0.0), completed_sources_progress)
                    job.products_success += len(valid_products)
                    job.products_error += len(unavailable_products)
                    progress_percent = 0.0
                    total = max(1, len(job.source_keys))
                    if total > 0:
                        progress_percent = (index / total) * 100.0
                    progress_percent = max(float(job.current_progress_percent or 0.0), progress_percent)
                    self._append_event(
                        job,
                        "source_progress",
                        {
                            "source_key": source_key,
                            "source_index": index,
                            "total_sources": len(job.source_keys),
                            "strategy": strategy,
                            "stage": stage,
                            "stage_code": stage_code.value,
                            "stage_label": self._stage_label(stage_code),
                            "products_success": job.products_success,
                            "products_error": job.products_error,
                            "progress_percent": round(progress_percent, 2),
                        },
                    )
                    self._append_event(
                        job,
                        "product_batch",
                        {
                            "batch_id": f"batch_{source_key}_{index}",
                            "source_key": source_key,
                            "strategy": strategy,
                            "stage": stage,
                            "items": all_products,
                        },
                    )
                    self._append_event(
                        job,
                        "source_finished",
                        {
                            "source_key": source_key,
                            "status": str(report.status.value),
                            "strategy": strategy,
                            "stage": stage,
                            "stage_code": stage_code.value,
                            "stage_label": self._stage_label(stage_code),
                            "valid_products": len(valid_products),
                            "unavailable_products": len(unavailable_products),
                        },
                    )
                    job.processed_sources = max(job.processed_sources, index)
                if str(report.status.value).lower() == "failed":
                    failed_sources += 1
            except Exception as exc:  # noqa: BLE001
                failed_sources += 1
                with self._lock:
                    job = self._jobs[job_id]
                    job.products_error += 1
                    self._append_event(
                        job,
                        "source_finished",
                        {
                            "source_key": source_key,
                            "status": "failed",
                            "stage": "failed",
                            "stage_code": SyncStageCode.SOURCE_FAILED.value,
                            "stage_label": self._stage_label(SyncStageCode.SOURCE_FAILED),
                            "error": str(exc),
                        },
                    )
            finally:
                unsubscribe_run_events(progress_run_id, _on_strategy_progress)

        with self._lock:
            job = self._jobs[job_id]
            if job.cancel_requested:
                job.status = "cancelled"
                self._append_event(
                    job,
                    "job_cancelled",
                    {"reason": "cancel_requested", "stage_code": SyncStageCode.JOB_CANCELLED.value, "stage_label": self._stage_label(SyncStageCode.JOB_CANCELLED)},
                )
            elif failed_sources > 0:
                job.status = "failed"
                self._append_event(
                    job,
                    "job_failed",
                    {"failed_sources": failed_sources, "stage_code": SyncStageCode.JOB_FAILED.value, "stage_label": self._stage_label(SyncStageCode.JOB_FAILED)},
                )
            else:
                job.status = "completed"
                self._append_event(job, "job_finished", {"stage_code": SyncStageCode.JOB_DONE.value, "stage_label": self._stage_label(SyncStageCode.JOB_DONE)})
            job.finished_at = _utcnow()
            job.current_stage = job.status
            if self._active_job_id == job.job_id:
                self._active_job_id = None
