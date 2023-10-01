"""Package of routes to interact with the API along."""
# External Party
from fastapi import APIRouter

from .builds import ROUTER as BUILD_ROUTER
from .products import ROUTER as PRODUCT_ROUTER
from .tools import ROUTER as TOOL_ROUTER

ROUTER = APIRouter()
ROUTER.include_router(PRODUCT_ROUTER)
ROUTER.include_router(TOOL_ROUTER)
ROUTER.include_router(BUILD_ROUTER)

_all = [ROUTER]
