"""Package of routes to interact with the API along."""
# External Party
from fastapi import APIRouter

from .products import ROUTER as PRODUCT_ROUTER
from .tools import ROUTER as TOOL_ROUTER

router = APIRouter()
router.include_router(PRODUCT_ROUTER)
router.include_router(TOOL_ROUTER)
