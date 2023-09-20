# Standard Library
from typing import Annotated
from typing import Any

# External Party
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from pydantic import BaseModel

# Local Modules
from inven_api.database.models import Tools
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

ROUTER = APIRouter(prefix="/tools", tags=["tools"])


def tool_query(
    name: Annotated[str | None, Query()] = None,
    vendor: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Define query parameters specific to tools.

    Args:
        name (str, optional): Name of tool to get. Defaults to None.
        vendor (str, optional): Get tools by this vendor. Defaults to None.

    Returns:
        dict[str, Any]: dictionary mapping of these query params
    """
    return {"name": name, "vendor": vendor}


def _apply_spec_statement(sql, specs: dict[str, Any]):
    """Apply results of `product_query` to a SQLALchemy statement.

    Args:
        sql: SQLAlchemy statement
        specs (dict[str, Any]): specifications loaded from query params

    Returns:
        modified SQL statement
    """
    key_column_map = {
        "name": Tools.name,
        "vendor": Tools.vendor,
    }
    for key, val in specs.items():
        if val is None:
            continue
        sql = sql.where(key_column_map[key] == val)

    return sql


ToolDep = Annotated[dict[str, Any], Depends(tool_query)]


class ToolCreate(BaseModel):
    """Define a Tool to be parsed from an incoming HTTP request.

    Very similar to the Tools in ../database/models.py.
    """

    name: str
    vendor: str
    owned: int
    avail: int


class ToolUpdate(BaseModel):
    """Define what fields can be updated on a Tool."""

    owned: int | None = None
    avail: int | None = None
    # TODO: singular plus minus on the above
    # like a checkin of a tool updating avail to be plus one


class ToolFull(ToolCreate):
    """Define a Tool for serializing as response to HTTP request.

    Just adds 'id' field which is necessary for responses.
    """

    tool_id: int


@ROUTER.get(path="")
async def get_all_tools(
    db: DatabaseDep, paginate: PaginationDep, tool_spec: ToolDep
) -> list[ToolFull]:
    """Read with all Tools matching query params and pagination."""
    ...


@ROUTER.get(path="/{tool_id}")
async def get_single_tool(tool_id: int, db: DatabaseDep) -> ToolFull:
    """Read the tool with the requested id."""
    ...


@ROUTER.delete(path="/{tool_id}")
async def remove_tool(tool_id: int, db: DatabaseDep) -> ToolFull:  # noqa: D103
    # TODO: should i use DELETE PUT to do the above TODO
    ...


@ROUTER.put(path="/{tool_id}")
async def update_tool(
    tool_id: int, db: DatabaseDep, update_data: ToolUpdate
) -> ToolFull:
    """Update the fields of a specific Tool."""
    ...
