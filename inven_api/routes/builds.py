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
from inven_api.database.models import BuildProducts
from inven_api.database.models import Builds
from inven_api.database.models import BuildTools
from inven_api.database.models import Products
from inven_api.database.models import ProductTypes
from inven_api.database.models import Tools
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


# Builds are unique in that they have an intersection against Parts and Tools
# This is a many-to-many relationship
# So we need to define a new route for this
# This is a sub-resource of Builds
class BuildRelationBase(BaseModel):
    """Model that defines the information needed to link a build to another table."""

    # validation alias since field name is not JSON like
    quantity_required: int = Field(gt=0, validation_alias="quantity")


class BuildProductCreate(BuildRelationBase):
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
    Even though this is a copy of BuildRelationBase, we need to define it
    seperately so that future changes to data models are easier.
    """

    # only quantity since product_id is not updatable
    quantity_required: int = Field(gt=0, validation_alias="quantity")


class BuildProductUpdate(BuildRelationUpdateBase):
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

    model_config = ConfigDict(from_attributes=True)

    build_id: int = Field(gt=0)


class ProductBuildLinkOut(BaseModel):
    """Product to nest into response when dealing with intersection routes.

    Inherits the 'quantity_required' field from BuildProducts table.
    """

    model_config = ConfigDict(from_attributes=True)

    product_id: int
    name: str
    vendor_sku: str
    product_type: ProductTypes
    quantity_required: int = Field(gt=0)


class ToolBuildLinkOut(BaseModel):
    """Tool to nest into response when dealing with intersection routes.

    Inherits the 'quantity_required' field from BuildTools table.
    """

    model_config = ConfigDict(from_attributes=True)

    tool_id: int
    name: str
    vendor: str
    quantity_required: int = Field(gt=0)


class BuildProductFullAll(BuildRelationFullBase):
    """Object to instantiate when resonding to BuildPart requests.

    Has array of products that a build is linked to.
    Each item of products has its corresponding quantity_required.
    """

    products: list[ProductBuildLinkOut]


class BuildProductFullSingle(BuildRelationFullBase):
    """Object to instantiate when resonding to BuildPart requests.

    Corresponds to response objects with a single product.
    """

    product: ProductBuildLinkOut


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


# or return {
# build_id: 1,
# products: [{
#   product_id: 1,
#   name: "hammer",
#   vednor sku: "1234",
#   product_type: "material",
# }],
# quantity: 10}
@build_part_router.get(
    path="", response_model=BuildProductFullAll, response_model_exclude_none=True
)
async def read_all_build_parts_for_id(
    build_id: int, session: DatabaseDep, page_choices: PaginationDep
):
    """Return all BuildParts present in database for a given build."""
    # only select the columns of the products table that are necessary
    build_product_exist_task = session.scalars(
        select(Builds).where(Builds.build_id == build_id)
    )
    sub_product_task = session.scalars(
        select(
            Products.product_id,
            Products.name,
            Products.product_type,
            Products.vendor_sku,
        )
        .select_from(join(BuildProducts, right=Products))
        .where(BuildProducts.build_id == build_id)
        .order_by(BuildProducts.product_id)
        .offset(page_choices["page"] * page_choices["limit"])
        .limit(page_choices["limit"])
    )
    if (await build_product_exist_task).one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
        )

    return {
        "build_id": build_id,
        "products": (await sub_product_task).all(),
    }


@build_part_router.get(
    path="/{product_id}",
    response_model=BuildProductFullSingle,
    response_model_exclude_none=True,
)
async def read_build_part_for_id(build_id: int, product_id: int, session: DatabaseDep):
    """Return a BuildPart present in database for a given build."""
    result = await session.execute(
        select(
            BuildProducts.quantity_required,
            Products.product_id,
            Products.name,
            Products.vendor_sku,
            Products.product_type,
        ).where(
            BuildProducts.build_id == build_id, BuildProducts.product_id == product_id
        )
    )
    build_product = result.one_or_none()
    if build_product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build Product pair not found"
        )
    return {
        "build_id": build_id,
        # build_product is now left with only the product values
        "product": build_product,
    }


@build_part_router.delete(path="/{product_id}", response_model=BuildProductFullSingle)
async def delete_build_part_for_id(
    build_id: int, product_id: int, session: DatabaseDep
):
    """Delete a BuildPart present in database for a given build.

    Even though this response model contains the product information,
    it does not delete the product from the product table.
    """
    async with session.begin():
        result = await session.scalars(
            delete(BuildProducts)
            .where(BuildProducts.product_id == Products.product_id)
            .where(
                BuildProducts.build_id == build_id,
                Products.product_id == product_id,
            )
            .returning(BuildProducts.quantity_required, Products.__table__.columns)
        )
        deleted_buildproduct = result.one_or_none()
        if deleted_buildproduct is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Build Product pair not found",
            )
        # auto commit
    return {
        "build_id": build_id,
        "product": deleted_buildproduct,
    }


@build_part_router.post(path="", response_model=BuildProductFullSingle)
async def add_buildpart_to_build(
    build_id: int, new_part: Annotated[BuildProductCreate, Body()], session: DatabaseDep
):
    """Add a BuildPart to a Build.

    This is a endpoint for adding a product to a build. This means that user already
    knows what build to add onto (knowing the build_id).
    """
    # TODO: make a general new build with products endpoint
    # now get the product information
    prod_result = session.scalars(
        select(Products).where(Products.product_id == new_part.product_id)
    )
    build_result = session.scalars(select(Builds).where(Builds.build_id == build_id))
    linked_product = (await prod_result).one_or_none()
    if linked_product is None:
        # have to close outstanding tasks if we won't await them
        build_result.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    # different message for each condition
    linked_build = (await build_result).one_or_none()
    if linked_build is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
        )
    added_obj = BuildProducts(build_id=build_id, **new_part.model_dump())
    async with session.begin():
        session.add(added_obj)
        await session.commit()
    return {
        "build_id": build_id,
        "quantity_required": new_part.quantity_required,
        "product": linked_product,
    }


@build_part_router.put(path="/{product_id}", response_model=BuildProductFullSingle)
async def update_buildpart_for_build(
    build_id: int,
    product_id: int,
    new_part: Annotated[BuildProductUpdate, Body()],
    session: DatabaseDep,
):
    """Update a BuildProduct of a Build.

    Only field updateable for BuildProduct is its quantity required.
    """
    async with session.begin():
        statement = (
            update(BuildProducts)
            .where(
                BuildProducts.build_id == build_id,
                BuildProducts.product_id == product_id,
            )
            .values(quantity_required=new_part.quantity_required)
            .returning(BuildProducts)
        )
        result = await session.execute(statement)
        result = result.scalar_one_or_none()
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Build Product not found"
            ) from None
        product_result = session.scalars(
            select(Products).where(Products.product_id == product_id)
        )
        await session.commit()

    return {
        "build_id": build_id,
        "quantity_required": new_part.quantity_required,
        "product": (await product_result).one(),
    }


# TODO: implement intersection point for tools
# The same many many intersection exists for tools
# So this path will respond with objects that look like:
# {
# build_id: 1,
# tool: {
#   tool_id: 1,
#   name: "hammer",
#   vendor: "home depot",
# },
# quantity: 10}
@build_tool_router.get(path="", response_model=BuildToolFullAll)
async def get_all_buildtools_for_id(
    build_id: int, session: DatabaseDep, pagination: PaginationDep
):
    """Return all BuildTools present in database for a given build."""
    result = session.scalars(
        select(BuildTools.quantity_required, Tools)
        .select_from(join(BuildTools, Tools))
        .where(BuildTools.build_id == build_id)
        .order_by(BuildTools.tool_id)
        .offset(pagination["page"] * pagination["limit"])
        .limit(pagination["limit"])
    )
    build_id_task = session.execute(
        select(BuildTools.build_id).where(Builds.build_id == build_id).limit(1)
    )
    if (await build_id_task).scalar_one_or_none() is None:
        result.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
        )
    return {
        "build_id": build_id,
        "tools": (await result).all(),
    }


@build_tool_router.get(path="/{tool_id}", response_model=BuildToolFullSingle)
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


@build_tool_router.delete(path="/{tool_id}", response_model=BuildToolFullSingle)
async def delete_buildtool_by_id(build_id: int, tool_id: int, session: DatabaseDep):
    """Delete a BuildTool present in database for a given build."""
    async with session.begin():
        result = await session.scalars(
            delete(BuildTools)
            .where(BuildTools.tool_id == Tools.tool_id)
            .where(
                BuildTools.build_id == build_id,
                Tools.tool_id == tool_id,
            )
            .returning(BuildTools.quantity_required, Tools.__table__.columns)
        )
        deleted_buildtool = result.one_or_none()
        if deleted_buildtool is None:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Build Tool pair not found",
            )
        # auto commit
    return {
        "build_id": build_id,
        "tool": deleted_buildtool,
    }


@build_tool_router.post(path="", response_model=BuildToolFullSingle)
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
            if e.orig.pgcode == ASYNCPG_UNIQUE_VIOLATION_CODE:  # type: ignore
                # repeated sku
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Build Tool pair already exists",
                ) from None
            if e.orig.pgcode == ASYNCPG_FK_VIOLATION_CODE:  # type: ignore
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
        "tool": tool_details.scalar_one(),
    }


@build_tool_router.put(path="/{tool_id}", response_model=BuildToolFullSingle)
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
            .returning(BuildTools.quantity_required, Tools.__table__.columns)
        )
        result = await session.scalars(statement)
        build_tool_result = result.one_or_none()
        if build_tool_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Build Tool not found"
            ) from None
        # auto commit
    return {
        "build_id": build_id,
        "tool": build_tool_result,
    }
