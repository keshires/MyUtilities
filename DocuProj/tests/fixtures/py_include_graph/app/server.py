from fastapi import FastAPI

from app.routers import api
from app.routers.loans import loan_router

CTX = "entity"


def setup():
    app = FastAPI()
    app.include_router(api.router, prefix=f"/{CTX}")
    app.include_router(loan_router, prefix="/loans")
    return app
