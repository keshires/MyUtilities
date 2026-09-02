from fastapi import APIRouter

v2 = APIRouter(prefix="/edfx/v2")


@v2.get("/tools/customPd")
async def custom_pd():
    return {}
