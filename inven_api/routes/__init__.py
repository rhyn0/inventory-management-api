"""Package of routes to interact with the API along."""
# External Party
from fastapi import APIRouter

from .products import ROUTER as PRODUCT_ROUTER

router = APIRouter()
router.include_router(PRODUCT_ROUTER)
