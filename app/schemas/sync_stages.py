from __future__ import annotations

from enum import Enum


class SyncStageCode(str, Enum):
    SOURCE_PREPARE = "source_prepare"
    DISCOVER_PRODUCTS = "discover_products"
    DISCOVER_DONE = "discover_done"
    FETCH_START = "fetch_start"
    FETCH_PROGRESS = "fetch_progress"
    FETCH_SKIP = "fetch_skip"
    EXPORT_PRODUCTS = "export_products"
    STRATEGY_RUN = "strategy_run"
    SOURCE_DONE = "source_done"
    SOURCE_FAILED = "source_failed"
    JOB_DONE = "job_done"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"


STAGE_LABEL_RU: dict[SyncStageCode, str] = {
    SyncStageCode.SOURCE_PREPARE: "Подготовка источника",
    SyncStageCode.DISCOVER_PRODUCTS: "Поиск списка товаров",
    SyncStageCode.DISCOVER_DONE: "Список товаров собран",
    SyncStageCode.FETCH_START: "Запуск загрузки карточек",
    SyncStageCode.FETCH_PROGRESS: "Загрузка карточек товаров",
    SyncStageCode.FETCH_SKIP: "Пропуск проблемного товара",
    SyncStageCode.EXPORT_PRODUCTS: "Экспорт карточек товаров",
    SyncStageCode.STRATEGY_RUN: "Выполнение стратегии",
    SyncStageCode.SOURCE_DONE: "Источник обработан",
    SyncStageCode.SOURCE_FAILED: "Ошибка обработки источника",
    SyncStageCode.JOB_DONE: "Синхронизация завершена",
    SyncStageCode.JOB_FAILED: "Синхронизация завершена с ошибками",
    SyncStageCode.JOB_CANCELLED: "Синхронизация отменена",
}
