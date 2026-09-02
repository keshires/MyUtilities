from fastapi import APIRouter

PFX = "/v1"

router = APIRouter()


@router.get(path=PFX + "/items")
async def items():
    return []
