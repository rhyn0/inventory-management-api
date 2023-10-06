"""File for starting the REST server."""
# Standard Library
from contextlib import asynccontextmanager
import logging
from logging.config import dictConfig

# External Party
from fastapi import FastAPI

# Local Modules
from inven_api.common import LOG_NAME
from inven_api.common import LogConfig
from inven_api.routes import ROUTER as SUB_ROUTER

LOG = None


@asynccontextmanager
async def api_lifespan(app: FastAPI):
    """Function to be called when the server starts and stops."""
    global LOG
    log_config = LogConfig(LOGGER_NAME=LOG_NAME, LOG_LEVEL="INFO")  # type: ignore
    dictConfig(log_config.model_dump())
    LOG = logging.getLogger(LOG_NAME)
    yield


APP = FastAPI(lifespan=api_lifespan)
APP.include_router(SUB_ROUTER)
