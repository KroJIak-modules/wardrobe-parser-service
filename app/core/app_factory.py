import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.services.source_registry_bootstrap_service import SourceRegistryBootstrapService


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    )
    app = FastAPI(title=settings.service_name)

    origins = [o.strip() for o in settings.cors_allowed_origins.split(',') if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    @app.on_event("startup")
    def bootstrap_source_registry() -> None:
        try:
            SourceRegistryBootstrapService().ensure_backend_seeded()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("Source registry bootstrap skipped: %s", exc)

    app.include_router(api_router)
    return app
