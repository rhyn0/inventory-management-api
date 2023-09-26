"""Package of routes to interact with the API along."""
# External Party
from fastapi import APIRouter

from .builds import ROUTER as BUILD_ROUTER
from .products import ROUTER as PRODUCT_ROUTER

router = APIRouter()
router.include_router(PRODUCT_ROUTER)
router.include_router(BUILD_ROUTER)
