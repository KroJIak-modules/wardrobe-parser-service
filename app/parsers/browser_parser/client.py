"""Subprocess client for browser-parser runner."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.parsers.browser_parser.models import BrowserParserDiscoveryPayload


_service_root = Path(__file__).resolve().parents[3]


class BrowserParserRunnerClient:
    """Execute Node.js browser-parser runner and return typed payload."""

    @staticmethod
    def _resolve_script_path() -> Path:
        raw = settings.parser_browser_script_path.strip()
        if not raw:
            raise ValidationError("PARSER_BROWSER_SCRIPT_PATH не задан")
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

    @classmethod
    def _build_command(cls, *, base_url: str) -> list[str]:
        script_path = cls._resolve_script_path()
        return [
            settings.parser_browser_node_bin,
            str(script_path),
            "--base-url",
            base_url,
            "--browser-binary",
            settings.parser_browser_binary,
            "--show-ui",
            "false",
            "--max-sitemaps",
            str(settings.parser_browser_max_product_sitemaps),
            "--js-sample-size",
            str(settings.parser_browser_js_sample_size),
            "--export-products",
            "true",
            "--export-concurrency",
            str(settings.parser_browser_export_concurrency),
            "--force-live-fallback",
            str(settings.parser_browser_force_live_fallback).lower(),
            "--wait-extension-timeout-ms",
            str(settings.parser_browser_wait_extension_timeout_ms),
        ]

    @staticmethod
    def _resolve_timeout(deadline_monotonic: float | None) -> float:
        requested = float(settings.parser_browser_process_timeout_sec)
        if deadline_monotonic is None:
            return requested
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("SOURCE_TIMEOUT before browser-parser run started")
        return max(1.0, min(requested, remaining))

    @classmethod
    def run(
        cls,
        *,
        base_url: str,
        deadline_monotonic: float | None = None,
    ) -> BrowserParserDiscoveryPayload:
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
            raise TimeoutError(f"browser-parser timeout: {exc}") from exc
        except FileNotFoundError as exc:
            raise ValidationError(
                f"browser-parser runtime не найден: {settings.parser_browser_node_bin}"
            ) from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise ValidationError(f"browser-parser failed: {detail}")
        if not stdout:
            raise ValidationError("browser-parser returned empty output")

        payload = None
        for line in reversed(stdout.splitlines()):
            candidate = line.strip()
            if not candidate:
                continue
            if not candidate.startswith("{"):
                continue
            try:
                payload = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if payload is None:
            raise ValidationError("browser-parser returned invalid JSON payload")

        result = BrowserParserDiscoveryPayload.model_validate(payload)
        if stderr:
            warnings = list(result.warnings or [])
            warnings.append(f"runner stderr: {stderr[:500]}")
            result.warnings = warnings
        return result

