from fastapi import APIRouter

from app.api.v1.sync import router as sync_router

api_router = APIRouter(prefix='/api/v1')
api_router.include_router(sync_router)
