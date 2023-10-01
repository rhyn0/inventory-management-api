"""File for starting the REST server."""
# External Party
from fastapi import FastAPI

from .routes import ROUTER as SUB_ROUTER

APP = FastAPI()
APP.include_router(SUB_ROUTER)


@APP.get("/")
def index():
    """Return the root level information about the project."""
    return {"message": "Inventory Management API"}
