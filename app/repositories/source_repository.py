from dataclasses import dataclass


@dataclass
class SourceRecord:
    id: int
    key: str
    url: str
    adapter_key: str
    enabled: bool
    sync_enabled: bool
    config: dict


class SourceRepository:
    """Stub repository for stage-1 architecture bootstrap."""

    def get_by_key(self, source_key: str) -> SourceRecord:
        # Stage-1: explicit config is required; no silent defaults.
        return SourceRecord(
            id=1,
            key=source_key,
            url='https://example.invalid',
            adapter_key='jadedldn__v1',
            enabled=True,
            sync_enabled=True,
            config={
                'strategy_sequence': ['noop'],
                'retry_limits': {'noop': 0},
                'timeouts': {'product_sec': 10, 'source_run_sec': 300},
            },
        )
