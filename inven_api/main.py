"""File for starting the REST server."""
# External Party
from fastapi import FastAPI

from .routes import PRODUCT_ROUTER

APP = FastAPI()
APP.include_router(PRODUCT_ROUTER)


@APP.get("/")
def index():
    """Return the root level information about the project."""
    return {"message": "Inventory Management API"}
