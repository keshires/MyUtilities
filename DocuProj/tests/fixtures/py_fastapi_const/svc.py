from fastapi import APIRouter

CTX = "/entity/v1"
RESOLVE = "/resolve"

router = APIRouter(prefix=CTX)


@router.get(RESOLVE)
async def resolve():
    return {}


@router.post(CTX + "/bulk")
async def bulk():
    return {}
