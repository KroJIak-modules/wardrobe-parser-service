from fastapi import APIRouter

from app.api.v1.parsers import router as parsers_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(parsers_router, prefix="/parsers", tags=["parsers"])
