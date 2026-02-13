import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import IntegrityError, NotFoundError, ValidationError
from app.services.parser_worker import ParserWorker

app = FastAPI(title="Wardrobe Parser Service API")

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


@app.get("/health", summary="Health check")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(NotFoundError)
def not_found_handler(request: object, exc: NotFoundError) -> None:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
def validation_handler(request: object, exc: ValidationError) -> None:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
def integrity_handler(request: object, exc: IntegrityError) -> None:
    return JSONResponse(status_code=409, content={"detail": str(exc)})

_local_origins = [
    "http://localhost:10530",
    "http://127.0.0.1:10530",
]

_extra_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_local_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.on_event("startup")
def start_sync_worker() -> None:
    parser_worker = ParserWorker(settings.sync_interval_sec)
    parser_worker.start()
    app.state.parser_worker = parser_worker


@app.on_event("shutdown")
def stop_sync_worker() -> None:
    parser_worker = getattr(app.state, "parser_worker", None)
    if parser_worker:
        parser_worker.stop()
