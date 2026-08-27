from __future__ import annotations

import json

from app.repositories.source_seed_repository import SourceSeedRepository


def test_source_seed_repository_loads_runtime_contract_without_adapter_metadata(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": 1,
                        "key": "example.test",
                        "url": "https://example.test",
                        "adapter_key": "example__v1",
                        "enabled": True,
                        "sync_enabled": True,
                        "config": {"mode": "manual", "strategy_sequence": ["example"]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    seeds = SourceSeedRepository(str(config_path)).list_all()

    assert len(seeds) == 1
    assert seeds[0].key == "example.test"
    assert seeds[0].config == {"mode": "manual", "strategy_sequence": ["example"]}
