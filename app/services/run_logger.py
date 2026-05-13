from __future__ import annotations

from typing import Any
from threading import Lock


_SUBSCRIBERS: dict[str, list] = {}
_LOCK = Lock()


class RunLogger:
    def __init__(self, run_id: str | None) -> None:
        self.run_id = run_id or ''

    def event(self, event_name: str, **fields: Any) -> None:
        parts = [f'[job={self.run_id}]', event_name]
        for key, value in fields.items():
            parts.append(f'{key}={value}')
        print(' '.join(parts), flush=True)

    def strategy_event(self, event_name: str, strategy: str, **fields: Any) -> None:
        parts = [f'[job={self.run_id}]', f'[{event_name}]', strategy]
        for key, value in fields.items():
            parts.append(f'{key}={value}')
        print(' '.join(parts), flush=True)
        if self.run_id:
            with _LOCK:
                callbacks = list(_SUBSCRIBERS.get(self.run_id, []))
            payload = {
                'type': event_name,
                'strategy': strategy,
                'fields': dict(fields),
            }
            for callback in callbacks:
                try:
                    callback(payload)
                except Exception:
                    # Logger callbacks must never break parser execution.
                    continue


def subscribe_run_events(run_id: str, callback) -> None:
    if not run_id:
        return
    with _LOCK:
        _SUBSCRIBERS.setdefault(run_id, []).append(callback)


def unsubscribe_run_events(run_id: str, callback) -> None:
    if not run_id:
        return
    with _LOCK:
        callbacks = _SUBSCRIBERS.get(run_id)
        if not callbacks:
            return
        _SUBSCRIBERS[run_id] = [cb for cb in callbacks if cb is not callback]
        if not _SUBSCRIBERS[run_id]:
            _SUBSCRIBERS.pop(run_id, None)
