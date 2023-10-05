"""Module containing routes for interacting with intersection table BuildProducts."""
# Standard Library
from typing import Annotated

# External Party
from fastapi import APIRouter
from fastapi import Body
from fastapi import HTTPException
from fastapi import status
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy import delete
from sqlalchemy import exc as sa_exc
from sqlalchemy import insert
from sqlalchemy import join
from sqlalchemy import select
from sqlalchemy import update

# Local Modules
from inven_api.database import ASYNCPG_FK_VIOLATION_CODE
from inven_api.database import ASYNCPG_UNIQUE_VIOLATION_CODE
from inven_api.database.models import Builds
from inven_api.database.models import BuildTools
from inven_api.database.models import Tools
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

from .http_models import BuildRelationBase
from .http_models import BuildRelationFullBase
from .http_models import BuildRelationUpdateBase

BUILD_TOOL_ROUTER = APIRouter(prefix="/{build_id}/tools", tags=["builds"])


class BuildToolCreate(BuildRelationBase):
    """Object to be instantiated when linking a build to a part."""

    # no additional columns needed
    tool_id: int


class BuildToolUpdate(BuildRelationUpdateBase):
    """Object to be instantiated when updating a BuildTool."""

    # no additional columns needed
    pass  # noqa: PIE790


class ToolBuildLinkOut(BaseModel):
    """Tool to nest into response when dealing with intersection routes.

    Inherits the 'quantity_required' field from BuildTools table.
    """

    model_config = ConfigDict(from_attributes=True)

    tool_id: int
    name: str
    vendor: str
    quantity_required: int = Field(gt=0)


class BuildToolFullAll(BuildRelationFullBase):
    """Object to instantiate when responding to BuildTool requests.

    Has array of tools that a build is linked to.
    Each item of tools has its corresponding quantity_required.
    """

    tools: list[ToolBuildLinkOut]


class BuildToolFullSingle(BuildRelationFullBase):
    """Object to instantiate when responding to BuildTool requests.

    Has array of tools that a build is linked to.
    """

    tool: ToolBuildLinkOut


@BUILD_TOOL_ROUTER.get(path="", response_model=BuildToolFullAll)
async def get_all_buildtools_for_id(
    build_id: int, session: DatabaseDep, pagination: PaginationDep
):
    """Return all BuildTools present in database for a given build."""
    result = session.execute(
        select(
            BuildTools.quantity_required,
            Tools.tool_id,
            Tools.name,
            Tools.vendor,
        )
        .select_from(join(BuildTools, Tools))
        .where(BuildTools.build_id == build_id)
        .order_by(BuildTools.tool_id)
        .offset(pagination["page"] * pagination["limit"])
        .limit(pagination["limit"])
    )
    build_id_task = session.execute(
        select(Builds.build_id).where(Builds.build_id == build_id).limit(1)
    )
    if (await build_id_task).scalar_one_or_none() is None:
        result.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
        )
    return {
        "build_id": build_id,
        "tools": (await result).t.all(),
    }


@BUILD_TOOL_ROUTER.get(path="/{tool_id}", response_model=BuildToolFullSingle)
async def get_buildtool_by_id(build_id: int, tool_id: int, session: DatabaseDep):
    """Return a BuildTool present in database for a given build."""
    result = await session.scalars(
        select(Tools, BuildTools.quantity_required)
        .select_from(join(BuildTools, Tools))
        .where(BuildTools.build_id == build_id, BuildTools.tool_id == tool_id)
    )
    build_tool = result.one_or_none()
    if build_tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build Tool pair not found"
        )
    return {
        "build_id": build_id,
        "tool": build_tool,
    }


@BUILD_TOOL_ROUTER.delete(path="/{tool_id}", response_model=BuildToolFullSingle)
async def delete_buildtool_by_id(build_id: int, tool_id: int, session: DatabaseDep):
    """Delete a BuildTool present in database for a given build."""
    schema_name = BuildTools.metadata.schema
    if schema_name is None:
        schema_name = ""
    else:
        schema_name += "."
    async with session.begin():
        result = await session.execute(
            delete(BuildTools)
            .where(BuildTools.tool_id == Tools.tool_id)
            .where(
                BuildTools.build_id == build_id,
                Tools.tool_id == tool_id,
            )
            # this returning only returns the deleted row
            # not the full state of the join to do this statement
            .returning(BuildTools.quantity_required)
        )
        deleted_buildtool = result.one_or_none()
        if deleted_buildtool is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Build Tool pair not found",
            )
        await session.commit()
        # pairing exists get remaining data from tools table
    tool_result = await session.scalars(select(Tools).where(Tools.tool_id == tool_id))

    return {
        "build_id": build_id,
        "tool": {
            **tool_result.one().__dict__,
            "quantity_required": deleted_buildtool.quantity_required,
        },
    }


@BUILD_TOOL_ROUTER.post(
    path="", response_model=BuildToolFullSingle, status_code=status.HTTP_201_CREATED
)
async def add_buildtool_to_build(
    build_id: int, new_tool: Annotated[BuildToolCreate, Body()], session: DatabaseDep
):
    """Add a BuildTool to a Build.

    BuildTools have a PK regarding the build_id and tool_id.
    Then FK constraints on both of those ids, so if uniqueness is not met
    or the values don't exist it can fail.
    """
    async with session.begin():
        statement = (
            insert(BuildTools)
            .values(
                build_id=build_id,
                tool_id=new_tool.tool_id,
                quantity_required=new_tool.quantity_required,
            )
            .returning(BuildTools)
        )
        tool_task = session.execute(
            select(Tools).where(Tools.tool_id == new_tool.tool_id)
        )
        try:
            await session.execute(statement)
        except sa_exc.IntegrityError as e:
            await session.rollback()
            # asyncpg error codes are do not have a good API
            # the best thing is to know the corresponding pgcode
            # for each error
            # for more info: https://github.com/MagicStack/asyncpg/
            # its in the exceptions folder somewhere
            # TODO: how to handle the variations of Integrity Error
            if e.orig.pgcode == ASYNCPG_UNIQUE_VIOLATION_CODE:  # type: ignore
                # repeated sku
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Build Tool pair already exists",
                ) from None
            if e.orig.pgcode == ASYNCPG_FK_VIOLATION_CODE:  # type: ignore
                # TODO: if Build is missing this should 404
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Build or Tool does not exist",
                ) from None
            # who knows what this was, needs to go to server logs
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unknown error",
            ) from e
        tool_details = await tool_task
        # autocommit
    return {
        "build_id": build_id,
        "tool": {
            **tool_details.scalar_one().__dict__,
            "quantity_required": new_tool.quantity_required,
        },
    }


@BUILD_TOOL_ROUTER.put(path="/{tool_id}", response_model=BuildToolFullSingle)
async def update_buildtool_for_build(
    build_id: int,
    tool_id: int,
    new_tool: Annotated[BuildToolUpdate, Body()],
    session: DatabaseDep,
):
    """Update a BuildTool of a Build.

    Only field updateable for BuildTool is its quantity required.
    """
    async with session.begin():
        statement = (
            update(BuildTools)
            .where(BuildTools.tool_id == Tools.tool_id)
            .where(
                BuildTools.build_id == build_id,
                # get the joint of the tables in one statement
                Tools.tool_id == tool_id,
            )
            .values(quantity_required=new_tool.quantity_required)
            .returning(BuildTools.quantity_required)
        )
        result = await session.execute(statement)
        build_tool_result = result.one_or_none()
        if build_tool_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Build Tool not found"
            ) from None
        # auto commit
    tool_result = await session.scalars(select(Tools).where(Tools.tool_id == tool_id))
    return {
        "build_id": build_id,
        "tool": {
            "quantity_required": build_tool_result.quantity_required,
            **tool_result.one().__dict__,
        },
    }
