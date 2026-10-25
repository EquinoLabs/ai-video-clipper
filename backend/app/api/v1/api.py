# API v1 router aggregate.

from fastapi import APIRouter
from app.api.v1.routes import health
from app.ai_clipper.api.routes import review as clipper_review
from app.ai_animation.api import routes as animation_routes

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(clipper_review.router)
api_v1_router.include_router(animation_routes.router)
