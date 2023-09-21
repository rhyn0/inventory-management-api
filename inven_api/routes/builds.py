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
from sqlalchemy import select

# Local Modules
from inven_api.database.models import Builds
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

ROUTER = APIRouter(prefix="/builds", tags=["builds"])


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
    build_sku: str


class BuildCreate(BuildBase):
    """Define a Build to be parsed from an incoming HTTP request."""


class BuildUpdate(BuildBase):
    """Make all fields in an update method optional.

    Might want to update only one of them.
    """

    name: str | None
    build_sku: str | None


class BuildFull(BuildBase):
    """Define a Build for serializing as response to HTTP request.

    Just adds 'id' field which is necessary for responses.
    """

    build_id: int


@ROUTER.get("", response_model=list[BuildFull])
async def read_all_builds(
    session: DatabaseDep,
    pagination: PaginationDep,
    product_spec: BuildDep,
):
    """Return all Products present in database."""
    statement = (
        select(Builds)
        .offset(pagination["page"] * pagination["limit"])
        .limit(pagination["limit"])
    )
    statement = _apply_spec_statement(statement, specs=product_spec)
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


@ROUTER.post("")
async def create_new_build(
    new_prod: Annotated[BuildBase, Body()], session: DatabaseDep
) -> BuildFull:
    """Take in data for a singular new build and add to database."""
    ...


@ROUTER.delete(path="/{build_id}")
async def delete_build_by_id(build_id: int, session: DatabaseDep) -> BuildFull:
    """Delete a build from database by it's ID.

    This delete has a cascade affect across other tables
    where the `build_id` is referenced.
    """
    ...


@ROUTER.patch(path="/{build_id}")
async def update_build_by_id(
    build_id: int, session: DatabaseDep, new_fields: BuildUpdate
) -> BuildFull:
    """Update fields of a Build based on input data.

    Not allowed to update the build_id.
    """
    ...
