"""Module containing request routes for interacting directly with Builds."""
# Standard Library
from typing import Annotated
from typing import Any

# External Party
from fastapi import APIRouter
from fastapi import Body
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import status
from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy import delete
from sqlalchemy import exc as sa_exc
from sqlalchemy import insert
from sqlalchemy import select
from sqlalchemy import update

# Local Modules
from inven_api.database.models import Builds
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

from .build_products import BUILD_PROD_ROUTER
from .build_tools import BUILD_TOOL_ROUTER

ROUTER = APIRouter(prefix="/builds", tags=["builds"])
ROUTER.include_router(BUILD_PROD_ROUTER)
ROUTER.include_router(BUILD_TOOL_ROUTER)


def build_query(
    name: Annotated[str | None, Query()] = None,
    sku: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Define query parameters specific to builds.

    Args:
        name (str, optional): Name of build to get. Defaults to None.
        sku (str, optional): Exact sku of build to get. Defaults to None.

    Returns:
        dict[str, Any]: dictionary mapping of these query params
    """
    return {"name": name, "sku": sku}


def _apply_spec_statement(sql, specs: dict[str, Any]):
    """Apply results of `build_query` to a SQLALchemy statement.

    Args:
        sql: SQLAlchemy statement
        specs (dict[str, Any]): specifications loaded from query params

    Returns:
        modified SQL statement
    """
    key_column_map = {
        "name": Builds.name,
        "sku": Builds.sku,
    }
    for key, val in specs.items():
        if val is None:
            continue
        sql = sql.where(key_column_map[key] == val)

    return sql


BuildDep = Annotated[dict[str, Any], Depends(build_query)]


# things to think about when defining this model
# there is the client version, and the database version
# have to figure out what we can securely show client
# https://stackoverflow.com/a/65907609
class BuildBase(BaseModel):
    """Define shared fields of all builds across any usage.

    Very similar to the Builds in ../database/models.py.
    """

    name: str
    sku: str


class BuildCreate(BuildBase):
    """Define a Build to be parsed from an incoming HTTP request."""

    # no extra colums needed
    pass  # noqa: PIE790


class BuildUpdateBase(BaseModel):
    """Define attributes of a Build that can be updated.

    Do not instantiate this one, should inherit instead.
    """

    name: str


class BuildUpdateIn(BuildUpdateBase):
    """Instantiable version of BuildUpdateBase.

    No additional columns.
    """

    pass  # noqa: PIE790


class BuildFull(BuildBase):
    """Define a Build for serializing as response to HTTP request.

    Just adds 'id' field which is necessary for responses.
    """

    model_config = ConfigDict(from_attributes=True)

    build_id: int


@ROUTER.get("", response_model=list[BuildFull])
async def read_all_builds(
    session: DatabaseDep,
    pagination: PaginationDep,
    build_spec: BuildDep,
):
    """Return all Products present in database."""
    statement = (
        select(Builds)
        .offset(pagination["page"] * pagination["limit"])
        .limit(pagination["limit"])
    )
    statement = _apply_spec_statement(statement, specs=build_spec)
    # sclars expands result columns into the tuple
    # otherwise will receive a tuple containing the Builds object
    result = await session.scalars(statement)
    # this is fine even if it returns 0
    return result.all()


@ROUTER.get("/{build_id}")
async def read_build_by_id(
    build_id: int,
    session: DatabaseDep,
) -> BuildFull:
    """Return a Build present in database.

    Does not use pagination dependency as up to one result only.
    """
    result = (
        await session.scalars(select(Builds).where(Builds.build_id == build_id))
    ).one_or_none()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not Found"
        )
    return result  # type: ignore


@ROUTER.post("", response_model=BuildFull, status_code=status.HTTP_201_CREATED)
async def create_new_build(
    new_prod: Annotated[BuildCreate, Body()], session: DatabaseDep
):
    """Take in data for a singular new build and add to database."""
    # insert the build, integrity error if the sku exists
    async with session.begin():
        statement = (
            insert(Builds)
            .values(
                name=new_prod.name,
                sku=new_prod.sku,
            )
            .returning(Builds)
        )
        try:
            result = await session.execute(statement)
        except sa_exc.IntegrityError:
            # repeated sku
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"SKU {new_prod.sku} already exists",
            ) from None
        # get the id of the newly inserted build
    return result.scalar_one()


@ROUTER.delete(path="/{build_id}", response_model=BuildFull)
async def delete_build_by_id(build_id: int, session: DatabaseDep):
    """Delete a build from database by it's ID.

    This delete has a cascade affect across other tables
    where the `build_id` is referenced.
    Return 404 if the build_id does not exist.
    """
    async with session.begin():
        statement = delete(Builds).where(Builds.build_id == build_id).returning(Builds)
        result = await session.execute(statement)
        result = result.scalar_one_or_none()
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
            )
    return result


@ROUTER.put(path="/{build_id}", response_model=BuildFull)
async def update_build_by_id(
    build_id: int, session: DatabaseDep, new_fields: Annotated[BuildUpdateIn, Body()]
):
    """Update fields of a Build based on input data.

    Not allowed to update the build_id or sku.
    So can only update the name.
    """
    async with session.begin():
        statement = (
            update(Builds)
            .where(Builds.build_id == build_id)
            .values(name=new_fields.name)
            .returning(Builds)
        )
        result = await session.execute(statement)
        result = result.scalar_one_or_none()
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
            ) from None
    return result
