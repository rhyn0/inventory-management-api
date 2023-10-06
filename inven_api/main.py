"""File for starting the REST server."""
# Standard Library
from contextlib import asynccontextmanager
import logging
from logging.config import dictConfig

# External Party
from fastapi import FastAPI

# Local Modules
from common import LogConfig
from routes import ROUTER as SUB_ROUTER

LOG = None
LOG_NAME = "api"


@asynccontextmanager
async def api_lifespan(app: FastAPI):
    """Function to be called when the server starts and stops."""
    global LOG, LOG_NAME
    log_config = LogConfig(LOGGER_NAME=LOG_NAME, LOG_LEVEL="INFO")  # type: ignore
    dictConfig(log_config.model_dump())
    LOG = logging.getLogger(LOG_NAME)
    yield


APP = FastAPI(lifespan=api_lifespan)
APP.include_router(SUB_ROUTER)


@APP.get("/")
def index():
    """Return the root level information about the project."""
    return {"message": "Inventory Management API"}
