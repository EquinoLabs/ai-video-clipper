"""API v1 router aggregate."""

from fastapi import APIRouter
from app.api.v1.routes import health, review

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(review.router)
