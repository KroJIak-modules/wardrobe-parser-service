from fastapi import APIRouter

from app.api.v1.shopify import router as shopify_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(shopify_router)
