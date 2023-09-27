"""Things that get litterd around."""
# Standard Library
from collections.abc import AsyncGenerator
from enum import StrEnum
from typing import Annotated
from typing import Any

# External Party
from fastapi import Depends
from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

# Local Modules
from inven_api.database import DbSession


class AtomicUpdateOperations(StrEnum):
    """Enum of atomic operations for updating an item's quantity field(s)."""

    INCREMENT = "increment"
    DECREMENT = "decrement"


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Spawn a session wherever it is needed."""
    db = DbSession()
    try:
        yield db
    finally:
        await db.close()


async def pagination_query(
    page: Annotated[int, Query()] = 0,
    page_size: Annotated[int, Query(gt=0)] = 5,
) -> dict[str, Any]:
    """Define pagination query parameters.

    Page means how many 'page_size' to skip.

    Args:
        page (Annotated[int, Query, optional): Page to start at. Defaults to 0.
        page_size (Annotated[int, Query, optional): Number of results. Defaults to 5.

    Returns:
        dict[str, Any]: mapping of these query params
    """
    return {"page": page, "limit": page_size}


DatabaseDep = Annotated[AsyncSession, Depends(get_db)]
PaginationDep = Annotated[dict[str, Any], Depends(pagination_query)]
