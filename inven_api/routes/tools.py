# Standard Library
from typing import Annotated
from typing import Any

# External Party
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import status
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy import exc as sa_exc
from sqlalchemy import select

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


class ToolBase(BaseModel):
    """Define a Tool to be parsed from an incoming HTTP request.

    Very similar to the Tools in ../database/models.py.
    This is a base class for ToolCreate and ToolUpdate.
    """

    name: str
    vendor: str
    owned: int
    avail: int


class ToolCreate(ToolBase):
    """Tool to be parsed from a POST request."""

    # No additional fields needed
    pass  # noqa: PIE790


class ToolUpdate(ToolBase):
    """Define what fields can be updated on a Tool."""

    owned: int | None = None
    avail: int | None = None
    # TODO: singular plus minus on the above
    # like a checkin of a tool updating avail to be plus one


class ToolFull(ToolBase):
    """Define a Tool for serializing as response to HTTP request.

    Just adds 'id' field which is necessary for responses.
    """

    tool_id: int


@ROUTER.get(path="", response_model=list[ToolFull])
async def get_all_tools(
    session: DatabaseDep, paginate: PaginationDep, tool_spec: ToolDep
):
    """Read with all Tools matching query params and pagination."""
    paginate_statement = select(Tools).offset(paginate["page"]).limit(paginate["limit"])
    return (
        await session.scalars(_apply_spec_statement(paginate_statement, tool_spec))
    ).all()


@ROUTER.get(path="/{tool_id}", response_model=ToolFull)
async def get_single_tool(tool_id: int, session: DatabaseDep):
    """Read the tool with the requested id."""
    result = (
        await session.execute(select(Tools).where(Tools.tool_id == tool_id))
    ).scalar_one_or_none()

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found"
        )

    return result


@ROUTER.delete(path="/{tool_id}", response_model=ToolFull)
async def remove_tool(tool_id: int, session: DatabaseDep):
    """Delete the tool with the requested id.

    If the tool has any builds that require it, it cannot be deleted.
    If tool does not exist, raise 404.
    """
    async with session.begin():
        try:
            result = (
                await session.execute(
                    delete(Tools).where(Tools.tool_id == tool_id).returning(Tools)
                )
            ).scalar_one_or_none()
        except sa_exc.IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="Tool is still needed for builds",
            ) from None

        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found"
            )

        return result


@ROUTER.put(path="/{tool_id}")
async def update_tool_quantity_set(
    tool_id: int, db: DatabaseDep, update_data: ToolUpdate
) -> ToolFull:
    """Update the quantity fields of a specific Tool.

    This is a set operation, not an increment. Based on provided body,
    this will set the field in database to given.
    """
    # TODO: other idea - use query params for the value
    ...
