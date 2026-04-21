"""Subprocess client for browser-parser runner."""

from __future__ import annotations

import json
import subprocess
import time
import logging
import threading
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.parsers.browser_parser.models import BrowserParserDiscoveryPayload


_service_root = Path(__file__).resolve().parents[3]
LOGGER = logging.getLogger(__name__)
_RUN_LOCK = threading.Lock()


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
    def _build_command(cls, *, base_url: str, export_concurrency: int | None = None) -> list[str]:
        script_path = cls._resolve_script_path()
        resolved_export_concurrency = (
            int(export_concurrency)
            if export_concurrency is not None
            else int(settings.parser_browser_export_concurrency)
        )
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
            str(max(1, resolved_export_concurrency)),
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
        export_concurrency: int | None = None,
    ) -> BrowserParserDiscoveryPayload:
        acquired = False
        wait_started = time.monotonic()
        while not acquired:
            if deadline_monotonic is not None:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("SOURCE_TIMEOUT waiting browser-parser lock")
                acquired = _RUN_LOCK.acquire(timeout=min(1.0, max(0.05, remaining)))
            else:
                acquired = _RUN_LOCK.acquire(timeout=1.0)
        wait_elapsed = time.monotonic() - wait_started
        if wait_elapsed >= 0.5:
            LOGGER.info("browser-parser lock acquired after %.2fs for %s", wait_elapsed, base_url)

        command = cls._build_command(base_url=base_url, export_concurrency=export_concurrency)
        timeout_sec = cls._resolve_timeout(deadline_monotonic)

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            _RUN_LOCK.release()
            raise ValidationError(
                f"browser-parser runtime не найден: {settings.parser_browser_node_bin}"
            ) from exc
        except Exception:
            _RUN_LOCK.release()
            raise

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_thread = threading.Thread(
            target=cls._read_pipe_lines,
            args=(process.stdout, stdout_lines),
            kwargs={"log_prefix": "[browser-parser] "},
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=cls._read_pipe_lines,
            args=(process.stderr, stderr_lines),
            kwargs={"log_prefix": "[browser-parser:stderr] "},
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            return_code = process.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired as exc:
            try:
                process.kill()
            except Exception:
                pass
            raise TimeoutError(f"browser-parser timeout: {exc}") from exc
        finally:
            stdout_thread.join(timeout=2.0)
            stderr_thread.join(timeout=2.0)
            try:
                _RUN_LOCK.release()
            except RuntimeError:
                pass

        stdout = "\n".join(stdout_lines).strip()
        stderr = "\n".join(stderr_lines).strip()
        if return_code != 0:
            detail = stderr or stdout or f"exit code {return_code}"
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
    @staticmethod
    def _read_pipe_lines(pipe, sink: list[str], *, log_prefix: str | None = None) -> None:
        if pipe is None:
            return
        try:
            for raw in pipe:
                line = (raw or "").rstrip()
                sink.append(line)
                if log_prefix and line:
                    LOGGER.info("%s%s", log_prefix, line)
        finally:
            try:
                pipe.close()
            except Exception:
                pass
