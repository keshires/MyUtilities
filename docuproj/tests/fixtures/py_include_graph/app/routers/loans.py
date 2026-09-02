from fastapi import APIRouter

loan_router = APIRouter()


@loan_router.get(path="/x")
async def lx():
    return []
