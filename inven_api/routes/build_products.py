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
from sqlalchemy import join
from sqlalchemy import select
from sqlalchemy import update

# Local Modules
from inven_api.database.models import BuildProducts
from inven_api.database.models import Builds
from inven_api.database.models import Products
from inven_api.database.models import ProductTypes
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

from .http_models import BuildRelationBase
from .http_models import BuildRelationFullBase
from .http_models import BuildRelationUpdateBase

BUILD_PROD_ROUTER = APIRouter(prefix="/{build_id}/products", tags=["builds"])


class BuildProductCreate(BuildRelationBase):
    """Object to be instantiated when linking a build to a part."""

    # no additional columns needed
    product_id: int


class BuildProductUpdate(BuildRelationUpdateBase):
    """Object to be instantiated when updating a BuildPart."""

    # no additional columns needed
    pass  # noqa: PIE790


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


class BuildProductFullSingle(BuildRelationFullBase):
    """Object to instantiate when resonding to BuildPart requests.

    Corresponds to response objects with a single product.
    """

    product: ProductBuildLinkOut


class BuildProductFullAll(BuildRelationFullBase):
    """Object to instantiate when resonding to BuildPart requests.

    Has array of products that a build is linked to.
    Each item of products has its corresponding quantity_required.
    """

    products: list[ProductBuildLinkOut]


@BUILD_PROD_ROUTER.get(
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
    sub_product_task = session.execute(
        select(
            Products.product_id,
            Products.name,
            Products.product_type,
            Products.vendor_sku,
            BuildProducts.quantity_required,
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
    products = (await sub_product_task).all()
    print(products)
    return {
        "build_id": build_id,
        "products": products,
    }


@BUILD_PROD_ROUTER.get(
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


@BUILD_PROD_ROUTER.delete(path="/{product_id}", response_model=BuildProductFullSingle)
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


@BUILD_PROD_ROUTER.post(path="", response_model=BuildProductFullSingle)
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


@BUILD_PROD_ROUTER.put(path="/{product_id}", response_model=BuildProductFullSingle)
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
