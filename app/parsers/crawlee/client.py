"""Subprocess client for Crawlee parser runner."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.parsers.crawlee.models import CrawleeDiscoveryPayload


_service_root = Path(__file__).resolve().parents[3]


class CrawleeRunnerClient:
    """Executes Node.js Crawlee runner and returns validated payload."""

    @staticmethod
    def _resolve_script_path() -> Path:
        raw = settings.parser_crawlee_script_path.strip()
        if not raw:
            raise ValidationError("PARSER_CRAWLEE_SCRIPT_PATH не задан")
        path = Path(raw)
        if path.is_absolute():
            return path
        candidates: list[Path] = [
            (Path.cwd() / path).resolve(),
            (_service_root / path).resolve(),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return (_service_root / path).resolve()

    @staticmethod
    def _build_command(*, base_url: str) -> list[str]:
        script_path = CrawleeRunnerClient._resolve_script_path()
        return [
            settings.parser_crawlee_node_bin,
            str(script_path),
            "--base-url",
            base_url,
            "--max-products",
            str(settings.parser_crawlee_max_products),
            "--timeout-ms",
            str(int(settings.parser_crawlee_timeout_sec * 1000)),
            "--max-discovery-pages",
            str(settings.parser_crawlee_max_discovery_pages),
            "--max-concurrency",
            str(settings.parser_crawlee_max_concurrency),
            "--max-retries",
            str(settings.parser_crawlee_max_retries),
        ]

    @staticmethod
    def _resolve_timeout(deadline_monotonic: float | None) -> float:
        requested = float(settings.parser_crawlee_process_timeout_sec)
        if deadline_monotonic is None:
            return requested
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("SOURCE_TIMEOUT before Crawlee run started")
        return max(1.0, min(requested, remaining))

    @classmethod
    def run(
        cls,
        *,
        base_url: str,
        deadline_monotonic: float | None = None,
    ) -> CrawleeDiscoveryPayload:
        command = cls._build_command(base_url=base_url)
        timeout_sec = cls._resolve_timeout(deadline_monotonic)

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"Crawlee parser timeout: {exc}") from exc
        except FileNotFoundError as exc:
            raise ValidationError(
                f"Crawlee runtime не найден: {settings.parser_crawlee_node_bin}"
            ) from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise ValidationError(f"Crawlee parser failed: {detail}")
        if not stdout:
            raise ValidationError("Crawlee parser returned empty output")

        payload = None
        # Crawlee may print technical logs before payload; parse last valid JSON line.
        for line in reversed(stdout.splitlines()):
            candidate = line.strip()
            if not candidate:
                continue
            if not candidate.startswith("{") and not candidate.startswith("["):
                continue
            try:
                payload = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if payload is None:
            raise ValidationError("Crawlee parser returned invalid JSON payload")

        result = CrawleeDiscoveryPayload.model_validate(payload)
        if stderr:
            warnings = list(result.warnings or [])
            warnings.append(f"runner stderr: {stderr[:500]}")
            result.warnings = warnings
        return result
