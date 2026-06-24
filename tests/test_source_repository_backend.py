from __future__ import annotations

from types import SimpleNamespace

import app.repositories.source_repository as repo_module
from app.repositories.source_repository import SourceRepository


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_source_repository_reads_runtime_sources_from_backend(monkeypatch) -> None:
    bootstrap_calls: list[str] = []

    monkeypatch.setattr(
        repo_module,
        "SourceRegistryBootstrapService",
        lambda: SimpleNamespace(ensure_backend_seeded=lambda: bootstrap_calls.append("seeded")),
    )
    monkeypatch.setattr(
        repo_module.requests,
        "get",
        lambda *args, **kwargs: DummyResponse(
            [
                {
                    "id": 7,
                    "key": "demo.example",
                    "url": "https://demo.example",
                    "adapter_key": "demo__v1",
                    "enabled": True,
                    "sync_enabled": False,
                    "config": {"mode": "manual"},
                }
            ]
        ),
    )

    repo = SourceRepository()
    items = repo.list_all()

    assert bootstrap_calls == ["seeded"]
    assert len(items) == 1
    assert items[0].key == "demo.example"
    assert items[0].adapter_key == "demo__v1"
    assert items[0].sync_enabled is False


def test_source_repository_get_by_key_raises_for_unknown_source(monkeypatch) -> None:
    monkeypatch.setattr(
        repo_module,
        "SourceRegistryBootstrapService",
        lambda: SimpleNamespace(ensure_backend_seeded=lambda: None),
    )
    monkeypatch.setattr(repo_module.requests, "get", lambda *args, **kwargs: DummyResponse([]))

    repo = SourceRepository()
    try:
        repo.get_by_key("missing.example")
    except KeyError as exc:
        assert str(exc) == "'missing.example'"
    else:
        raise AssertionError("KeyError not raised")


def test_source_repository_bootstrap_skips_seed_post_when_backend_registry_exists(monkeypatch) -> None:
    import app.services.source_registry_bootstrap_service as bootstrap_module
    from app.services.source_registry_bootstrap_service import SourceRegistryBootstrapService

    class DummyBootstrapResponse(DummyResponse):
        pass

    post_calls: list[dict] = []

    def fake_get(*args, **kwargs):
        return DummyBootstrapResponse(
            [
                {
                    "id": 1,
                    "key": "existing.example",
                    "url": "https://existing.example",
                    "adapter_key": "existing__v1",
                    "enabled": True,
                    "sync_enabled": True,
                    "config": {"mode": "auto"},
                }
            ]
        )

    def fake_post(*args, **kwargs):
        post_calls.append({"args": args, "kwargs": kwargs})
        return DummyBootstrapResponse({"ok": True})

    monkeypatch.setattr(bootstrap_module.requests, "get", fake_get)
    monkeypatch.setattr(bootstrap_module.requests, "post", fake_post)
    SourceRegistryBootstrapService._seeded = False

    try:
        SourceRegistryBootstrapService().ensure_backend_seeded()
    finally:
        SourceRegistryBootstrapService._seeded = False

    assert post_calls == []
