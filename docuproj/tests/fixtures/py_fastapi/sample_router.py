from fastapi import APIRouter

entity_router = APIRouter(prefix="/entities")


@entity_router.get("/{id}")
async def get_entity(id: str):
    return {"id": id}


@entity_router.post("")
async def create_entity():
    return {}


health_router = APIRouter()


@health_router.get("/health")
def health():
    return "ok"
