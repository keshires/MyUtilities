from fastapi import APIRouter

from app.routers.v1 import items_route

router = APIRouter()
router.include_router(items_route.router)
