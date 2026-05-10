from __future__ import annotations

from typing import Any


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
