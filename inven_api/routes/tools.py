# Standard Library
from enum import StrEnum
import logging
from operator import add
from operator import sub
from typing import Annotated
from typing import Any
from typing import Self

# External Party
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import status
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy import delete
from sqlalchemy import exc as sa_exc
from sqlalchemy import select
from sqlalchemy import update

# Local Modules
from inven_api.common import LOG_NAME
from inven_api.database.models import Tools
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

# redirect slashes means that if a client
# sends a request to /tools it is same as /tools/
ROUTER = APIRouter(prefix="/tools", tags=["tools"], redirect_slashes=True)

LOG = logging.getLogger(LOG_NAME + ".tools")


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
    owned: int = Field(validation_alias="total_owned")
    available: int = Field(validation_alias="total_avail")


class ToolCreate(ToolBase):
    """Tool to be parsed from a POST request."""

    # No additional fields needed
    pass  # noqa: PIE790


class ToolUpdatePaths(StrEnum):
    """Enum of paths for updating a tool's quantity fields."""

    OWNED = ("owned", "total_owned")
    AVAIL = ("available", "total_available")

    def __new__(cls, value: str, column_name: str) -> Self:
        """Override object creation to store the column name alongside the value."""
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.column_name = column_name  # type: ignore
        return obj


class ToolUpdateAtomicOperations(StrEnum):
    """Enum of atomic operations for updating a tool's quantity fields."""

    INCREMENT = "increment"
    DECREMENT = "decrement"


class ToolAtomicUpdateOutBase(BaseModel):
    """Define base object that can be returned from an atomic update operation."""

    tool_id: int
    total_owned: int | None
    total_avail: int | None


class ToolPreAtomicUpdate(ToolAtomicUpdateOutBase):
    """Define object that can be returned from a get pre-atomic update operation."""

    model_config = ConfigDict(from_attributes=True)

    # serialization_alias only used by FastAPI when response_model_by_alias=True
    total_owned: int | None = Field(serialization_alias="preTotalOwned")
    total_avail: int | None = Field(serialization_alias="preTotalAvail")


class ToolPostAtomicUpdate(ToolAtomicUpdateOutBase):
    """Define object that can be returned from a atomic update then get operation."""

    model_config = ConfigDict(from_attributes=True)

    total_owned: int | None = Field(serialization_alias="postTotalOwned")
    total_avail: int | None = Field(serialization_alias="postTotalAvail")


class ToolUpdate(BaseModel):
    """Define an update set operation for a Tool."""

    owned: int | None = Field(None, serialization_alias="total_owned")
    avail: int | None = Field(None, serialization_alias="total_avail")


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
    LOG.debug("Getting all tools - pagination: %s", paginate)
    paginate_statement = select(Tools).offset(paginate["page"]).limit(paginate["limit"])
    return (
        await session.scalars(_apply_spec_statement(paginate_statement, tool_spec))
    ).all()


@ROUTER.get(path="/{tool_id}", response_model=ToolFull)
async def get_single_tool(tool_id: int, session: DatabaseDep):
    """Read the tool with the requested id."""
    LOG.debug("Getting tool %s", tool_id)
    result = (
        await session.execute(select(Tools).where(Tools.tool_id == tool_id))
    ).scalar_one_or_none()

    if result is None:
        LOG.warning("Tool %s not found", tool_id)
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
    LOG.debug("Deleting tool %s", tool_id)
    async with session.begin():
        try:
            result = (
                await session.execute(
                    delete(Tools).where(Tools.tool_id == tool_id).returning(Tools)
                )
            ).scalar_one_or_none()
        except sa_exc.IntegrityError:
            await session.rollback()
            LOG.exception("Tool %s still needed for builds", tool_id)
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="Tool is still needed for builds",
            ) from None

        if result is None:
            LOG.warning("Tool %s not found", tool_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found"
            )

        return result


@ROUTER.put(path="/{tool_id}", response_model=ToolFull)
async def update_tool_quantity_set(
    tool_id: int, session: DatabaseDep, update_data: ToolUpdate
):
    """Update the quantity fields of a specific Tool.

    This is a set operation, not an increment. Based on provided body,
    this will set the field in database to given.
    """
    LOG.debug("Updating tool %s with %s", tool_id, update_data)
    async with session.begin():
        result = (
            await session.execute(
                select(Tools).where(Tools.tool_id == tool_id).with_for_update()
            )
        ).scalar_one_or_none()

        if result is None:
            await session.rollback()
            LOG.warning("Tool %s not found", tool_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool {tool_id} not found",
            )

        # Update the fields that were provided
        # exclude_unset=True will filter out the default None values
        # by_alias=True will use the serialization_alias which is the exact column name
        for field, value in update_data.model_dump(
            exclude_unset=True, by_alias=True
        ).items():
            setattr(result, field, value)
        try:
            await session.commit()
        except sa_exc.IntegrityError:
            # occurs when total_owned < total_avail
            await session.rollback()
            LOG.exception(
                "Owned must be greater than or equal to available - data %s",
                update_data,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Owned must be greater than or equal to available",
            ) from None
    return result


@ROUTER.put(
    path="/{tool_id}/{field}/{atomic_op}/get",
    response_model_by_alias=True,
    response_model=ToolPostAtomicUpdate,
)
async def update_tool_quantity_atomic_postget(
    tool_id: int,
    field: ToolUpdatePaths,
    atomic_op: ToolUpdateAtomicOperations,
    session: DatabaseDep,
    value: Annotated[int, Query(gt=0)] = 1,
):
    """Update the quantity owned fields of a specific Tool by an amount.

    Example:
        curl -X PUT .../tools/1/owned/increment/get?value=5

    This is an atomic update operation. Based on provided request path,
    this will increment/decrement the field in database by given value.
    Then return the new value.
    """
    LOG.debug("Updating tool %s with %s", tool_id, value)
    async with session.begin():
        result = (
            await session.execute(
                select(Tools).where(Tools.tool_id == tool_id).with_for_update()
            )
        ).scalar_one_or_none()

        if result is None:
            LOG.warning("Tool %s not found", tool_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool {tool_id} not found",
            )
        oper = add if atomic_op == ToolUpdateAtomicOperations.INCREMENT else sub
        if field is ToolUpdatePaths.OWNED:
            result.total_owned = oper(Tools.total_owned, value)
        else:
            result.total_avail = oper(Tools.total_avail, value)
        # auto commit
    await session.refresh(result, ["total_owned", "total_avail"])
    return result


@ROUTER.put(
    path="/{tool_id}/{field}/get/{atomic_op}",
    response_model_by_alias=True,
    response_model=ToolPreAtomicUpdate,
)
async def update_tool_quantity_atomic_preget(
    tool_id: int,
    field: ToolUpdatePaths,
    atomic_op: ToolUpdateAtomicOperations,
    session: DatabaseDep,
    value: Annotated[int, Query(gt=0)] = 1,
):
    """Update the quantity owned fields of a specific Tool by an amount.

    Example:
        curl -X PUT ../tools/1/owned/get/increment?value=5

    This is an atomic update operation. Based on provided request path,
    this will increment/decrement the field in database by given value.
    Then return the value prior to the execution.
    """
    LOG.debug("Updating tool %s with %s", tool_id, value)
    async with session.begin():
        result = (
            await session.execute(
                select(Tools).where(Tools.tool_id == tool_id).with_for_update()
            )
        ).scalar_one_or_none()

        if result is None:
            await session.rollback()
            LOG.warning("Tool %s not found", tool_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool {tool_id} not found",
            )
        # have to copy this out of the result
        # otherwise the session has a reference to the result
        # which will update the fields when executing the statement at end
        output_update = ToolPreAtomicUpdate(
            tool_id=result.tool_id,
            total_avail=result.total_avail,
            total_owned=result.total_owned,
        )
        oper = add if atomic_op == ToolUpdateAtomicOperations.INCREMENT else sub
        statement = update(Tools).where(Tools.tool_id == tool_id)
        if field is ToolUpdatePaths.OWNED:
            statement = statement.values(total_owned=oper(Tools.total_owned, value))
        else:
            statement = statement.values(total_avail=oper(Tools.total_avail, value))
        await session.execute(statement)
        # auto commit
    return output_update
