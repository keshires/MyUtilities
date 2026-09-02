from fastapi import APIRouter

PFX = "/v1"

r = APIRouter()


@r.get(path=PFX + "/items")
async def items():
    return []


def setup(app):
    # mount prefix applied per-router via include_router
    app.include_router(r, prefix="/svc")
