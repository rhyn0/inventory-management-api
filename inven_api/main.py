"""File for starting the REST server."""
# External Party
from fastapi import FastAPI

from .routes import router

APP = FastAPI()
APP.include_router(router)


@APP.get("/")
def index():
    """Return the root level information about the project."""
    return {"message": "Inventory Management API"}
