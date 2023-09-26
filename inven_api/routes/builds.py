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
from pydantic import Field
from sqlalchemy import delete
from sqlalchemy import exc as sa_exc
from sqlalchemy import insert
from sqlalchemy import select
from sqlalchemy import update

# Local Modules
from inven_api.database.models import Builds
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

build_part_router = APIRouter(prefix="/builds/{build_id}/parts", tags=["builds"])
build_tool_router = APIRouter(prefix="/builds/{build_id}/tools", tags=["builds"])
ROUTER = APIRouter(prefix="/builds", tags=["builds"])
ROUTER.include_router(build_part_router)
ROUTER.include_router(build_tool_router)


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
    """Define attributes of a Build that can be updated."""

    name: str


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
    build_id: int, session: DatabaseDep, new_fields: Annotated[BuildUpdateBase, Body()]
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


# Builds are unique in that they have an intersection against Parts and Tools
# This is a many-to-many relationship
# So we need to define a new route for this
# This is a sub-resource of Builds
class BuildRelationBase(BaseModel):
    """Model that defines the information needed to link a build to another table."""

    # validation alias since field name is not JSON like
    quantity_required: int = Field(gt=0, validation_alias="quantity")


class BuildPartCreate(BuildRelationBase):
    """Object to be instantiated when linking a build to a part."""

    # no additional columns needed
    product_id: int


class BuildToolCreate(BuildRelationBase):
    """Object to be instantiated when linking a build to a part."""

    # no additional columns needed
    tool_id: int


class BuildRelationUpdateBase(BaseModel):
    """Define attributes of a BuildPart that can be updated.

    Do not instantiate this, it is an inheritable base.
    """

    # only quantity since product_id is not updatable
    quantity_required: int = Field(gt=0, validation_alias="quantity")


class BuildPartUpdate(BuildRelationUpdateBase):
    """Object to be instantiated when updating a BuildPart."""

    # no additional columns needed
    pass  # noqa: PIE790


class BuildToolUpdate(BuildRelationUpdateBase):
    """Object to be instantiated when updating a BuildTool."""

    # no additional columns needed
    pass  # noqa: PIE790


class BuildRelationFullBase(BaseModel):
    """Define a Base Build for serializing as response to HTTP request.

    This is not to be instantiated, it is an inheritable base.
    """

    build_id: int
    quantity_required: int = Field(gt=0, serialization_alias="quantity")


class BuildPartFull(BuildRelationFullBase):
    """Object to instantiate when resonding to BuildPart requests."""

    product_id: int


class BuildToolFull(BuildRelationFullBase):
    """Object to instantiate when responding to BuildTool requests."""

    tool_id: int


# TODO: make design decision on whether to include full relation part or not
# so this request could return {build_id: 1, product_id: 1, quantity: 10}
# or return {build_id: 1, product: {product_id: 1, name: "hammer"}, quantity: 10}
# or even {
#   build_id: 1,
#   vendor: "HomeDepot",
#   product: {
#       product_id: 1,
#       name: "hammer"
#   },
#   quantity: 10}
@build_part_router.get(path="", response_model=list[BuildPartFull])
async def read_all_build_parts_for_id(build_id: int, session: DatabaseDep):
    """Return all BuildParts present in database for a given build."""
    ...


@build_part_router.get(path="/{product_id}", response_model=BuildPartFull)
async def read_build_part_for_id(build_id: int, product_id: int, session: DatabaseDep):
    """Return a BuildPart present in database for a given build."""
    ...


@build_part_router.delete(path="/{product_id}", response_model=BuildPartFull)
async def delete_build_part_for_id(
    build_id: int, product_id: int, session: DatabaseDep
):
    """Delete a BuildPart present in database for a given build."""
    ...


@build_part_router.post(path="", response_model=BuildPartFull)
async def add_buildpart_to_build(
    build_id: int, new_part: Annotated[BuildPartCreate, Body()], session: DatabaseDep
):
    """Add a BuildPart to a Build."""
    ...


@build_part_router.put(path="/{product_id}", response_model=BuildPartFull)
async def update_buildpart_for_build(
    build_id: int,
    product_id: int,
    new_part: Annotated[BuildPartUpdate, Body()],
    session: DatabaseDep,
):
    """Update a BuildPart of a Build."""
    ...


@build_tool_router.get(path="", response_model=list[BuildToolFull])
async def get_all_buildtools_for_id(build_id: int, session: DatabaseDep):
    """Return all BuildTools present in database for a given build."""
    ...


@build_tool_router.get(path="/{tool_id}", response_model=BuildToolFull)
async def get_buildtool_by_id(build_id: int, tool_id: int, session: DatabaseDep):
    """Return a BuildTool present in database for a given build."""
    ...


@build_tool_router.delete(path="/{tool_id}", response_model=BuildToolFull)
async def delete_buildtool_by_id(build_id: int, tool_id: int, session: DatabaseDep):
    """Delete a BuildTool present in database for a given build."""
    ...


@build_tool_router.post(path="", response_model=BuildToolFull)
async def add_buildtool_to_build(
    build_id: int, new_tool: Annotated[BuildToolCreate, Body()], session: DatabaseDep
):
    """Add a BuildTool to a Build."""
    ...


@build_tool_router.put(path="/{tool_id}", response_model=BuildToolFull)
async def update_buildtool_for_build(
    build_id: int,
    tool_id: int,
    new_tool: Annotated[BuildToolUpdate, Body()],
    session: DatabaseDep,
):
    """Update a BuildTool of a Build."""
    ...
