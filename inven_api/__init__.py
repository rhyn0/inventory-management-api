"""Inventory Management REST API project."""
# Standard Library
import logging

from .main import APP
from .main import LOG_NAME

__version__ = "0.8.0"

_all = [APP]
LOG = logging.getLogger(LOG_NAME)


@APP.get("/")
def index():
    """Return the root level information about the project."""
    LOG.info("Received request for root level information about API v%s.", __version__)
    return {"message": f"Inventory Management API v{__version__}"}
