"""Methods and routes for interacting with Products in Inventory Management API.

The products table in SQL is defined in ../database/models.py
"""
# Standard Library
import logging
from operator import add
from operator import sub
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
from sqlalchemy import select

# Local Modules
from inven_api.common import LOG_NAME
from inven_api.database import Products
from inven_api.database import ProductTypes
from inven_api.dependencies import AtomicUpdateOperations
from inven_api.dependencies import DatabaseDep
from inven_api.dependencies import PaginationDep

ROUTER = APIRouter(prefix="/products", tags=["products"])

LOG = logging.getLogger(LOG_NAME + ".products")


def product_query(
    name: Annotated[str | None, Query()] = None,
    vendor: Annotated[str | None, Query()] = None,
    product_type: Annotated[ProductTypes | None, Query()] = None,
    sku: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Define query parameters specific to products.

    Args:
        name (str, optional): Name of product to get. Defaults to None.
        vendor (str, optional): Get products by this vendor. Defaults to None.
        product_type (ProductTypes, optional): subset products to this type.
            Defaults to None.
        sku (str, optional): Exact sku of product to get. Defaults to None.

    Returns:
        dict[str, Any]: dictionary mapping of these query params
    """
    return {"name": name, "vendor": vendor, "type": product_type, "sku": sku}


def _apply_spec_statement(sql, specs: dict[str, Any]):
    """Apply results of `product_query` to a SQLALchemy statement.

    Args:
        sql: SQLAlchemy statement
        specs (dict[str, Any]): specifications loaded from query params

    Returns:
        modified SQL statement
    """
    key_column_map = {
        "name": Products.name,
        "vendor": Products.vendor,
        "type": Products.product_type,
        "sku": Products.vendor_sku,
    }
    for key, val in specs.items():
        if val is None:
            continue
        sql = sql.where(key_column_map[key] == val)

    return sql


ProductDep = Annotated[dict[str, Any], Depends(product_query)]


class ProductBase(BaseModel):
    """Define a Product to be parsed from an incoming HTTP request.

    Very similar to the Products in ../database/models.py.
    This is a shared base of the common fields, should not be instantiated.
    """

    name: str
    vendor: str
    product_type: ProductTypes
    vendor_sku: str
    quantity: int = Field(ge=0)  # can't have a negative quantity


class ProductCreate(ProductBase):
    """Model to be parsed from a create request."""

    # No extra columns to add
    pass  # noqa: PIE790


class ProductUpdate(BaseModel):
    """Define what fields can be updated on a Product."""

    quantity: int = Field(ge=0)


class ProductFull(ProductBase):
    """Define a Product for deserializing as response to HTTP request.

    Just adds 'id' field which is necessary for responses.
    """

    product_id: int


class ProductUpdateBase(BaseModel):
    """Define a Product that can be serialized out to a response.

    Very similar to the Products in ../database/models.py.
    This is a shared base of the common fields, should not be instantiated.

    Setting 'from_attributes' will help with validation
    from a SQLAlchemy Products item.
    """

    model_config = ConfigDict(from_attributes=True)

    product_id: int
    vendor_sku: str
    quantity: int | None = Field(default=None, ge=0)


class ProductPreUpdate(ProductUpdateBase):
    """Define a Product that can be serialized out to a response.

    This is used for update and get operations, where the get happens before update.
    """

    quantity: int = Field(ge=0, serialization_alias="preUpdateQuantity")


class ProductPostUpdate(ProductUpdateBase):
    """Define a Product that can be serialized out to a response.

    This is used for update and get operations, where the get happens after update.
    """

    quantity: int = Field(ge=0, serialization_alias="postUpdateQuantity")


@ROUTER.get("", response_model=list[ProductFull])
async def read_products(
    session: DatabaseDep,
    pagination: PaginationDep,
    product_spec: ProductDep,
):
    """Return all Products present in database.

    Can be affected by query params:
        - name: name of product to get
        - vendor: vendor of product to get
        - type: "part" or "material"
        - sku: exact sku of product to get, helpful if product_id is unknown

    Also uses pagination dependency to limit results.
    Default page is 0 with a page size of 5
    """
    LOG.debug("Getting all products - pagination: %s", pagination)
    statement = (
        select(Products)
        .select_from(Products)
        .offset(pagination["page"] * pagination["limit"])
        .limit(pagination["limit"])
    )
    statement = _apply_spec_statement(statement, specs=product_spec)
    # sclars expands result columns into the tuple
    # otherwise will receive a tuple containing the Products object
    result = await session.scalars(statement)
    # this is fine even if it returns 0
    return result.all()


@ROUTER.get("/{prod_id}", response_model=ProductFull)
async def read_product_by_id(
    prod_id: int,
    session: DatabaseDep,
):
    """Return a Product present in database.

    Does not use pagination dependency as up to one result only.
    """
    LOG.debug("Getting product %s", prod_id)
    result = (
        await session.scalars(select(Products).where(Products.product_id == prod_id))
    ).one_or_none()
    if result is None:
        LOG.warning("Product %s not found", prod_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return result


@ROUTER.post("", response_model=ProductFull, status_code=status.HTTP_201_CREATED)
async def insert_new_product(
    new_prod: Annotated[ProductCreate, Body()], session: DatabaseDep
):
    """Take in data for a singular new product and add to database."""
    LOG.debug("Creating new product %s", new_prod)
    async with session.begin():
        try:
            return await session.scalar(
                insert(Products).values(new_prod.model_dump()).returning(Products)
            )
        except sa_exc.IntegrityError:
            # integrity can be broken if vendor_sku is not unique
            await session.rollback()
            LOG.exception("Vendor SKU already exists - data %s", new_prod)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vendor SKU already exists",
            ) from None


@ROUTER.delete(path="/{prod_id}", response_model=ProductFull)
async def remove_product(prod_id: int, session: DatabaseDep):
    """Remove product from database.

    This will return the deleted product
    if there are no Builds relying upon this part.

    If there is such a constraint still, respond with 405
    """
    LOG.debug("Deleting product %s", prod_id)
    async with session.begin():
        try:
            result = (
                await session.scalars(
                    delete(Products)
                    .where(Products.product_id == prod_id)
                    .returning(Products)
                )
            ).one_or_none()
            if result is None:
                LOG.warning("Product %s not found", prod_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
                )

        except sa_exc.IntegrityError:
            await session.rollback()
            LOG.exception("Product %s still in use", prod_id)
            # This happens due to foreign key constraint
            # from table build_parts (BuildParts)
            # TODO: include the build_id in the response
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="Product is still part of an active build",
            ) from None

    return result


@ROUTER.put(path="/{prod_id}", response_model=ProductFull)
async def update_product(
    prod_id: int, updated_prod: Annotated[ProductUpdate, Body()], session: DatabaseDep
):
    """Update the quantity in bulk for a product.

    The thinking of this endpoint is that someone has just counted,
    the available stock of a product and is setting the current amount.
    """
    # quantity being less than 0 is handled by pydantic
    LOG.debug("Updating product %s with %s", prod_id, updated_prod)
    async with session.begin():
        tobe_updated_prod = (
            await session.execute(
                select(Products).where(Products.product_id == prod_id).with_for_update()
            )
        ).scalar_one_or_none()
        if tobe_updated_prod is None:
            LOG.warning("Product %s not found", prod_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        tobe_updated_prod.quantity = updated_prod.quantity
        await session.commit()
    return tobe_updated_prod


@ROUTER.put(
    path="/{prod_id}/quantity/{atomic_op}/get",
    response_model=ProductPostUpdate,
    response_model_by_alias=True,
)
async def update_product_quantity_atomic_postget(
    session: DatabaseDep,
    prod_id: int,
    atomic_op: AtomicUpdateOperations,
    value: Annotated[int, Query(gt=0)],
):
    """Update the quantity atomically and by a delta value for a Product.

    The thinking of this endpoint is that someone is taking out some items,
    they don't know the total leftover after their action but they know
    how many they took.

    There is no required JSON body.

    Returns:
        ProductPostUpdate: serialized Product with post update quantity
    """
    LOG.debug("Updating product %s with %s", prod_id, atomic_op)
    async with session.begin():
        tobe_updated_prod = (
            await session.execute(
                select(Products).where(Products.product_id == prod_id).with_for_update()
            )
        ).scalar_one_or_none()

        # check for nonexistence - 404
        if tobe_updated_prod is None:
            await session.rollback()
            LOG.warning("Product %s not found", prod_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        oper = add if atomic_op == AtomicUpdateOperations.INCREMENT else sub

        tobe_updated_prod.quantity = oper(Products.quantity, value)
        # auto commit
    # refresh to get the new value, can emit a Select statement
    await session.refresh(tobe_updated_prod, ["quantity"])
    return tobe_updated_prod


@ROUTER.put(
    path="/{prod_id}/quantity/get/{atomic_op}",
    response_model=ProductPreUpdate,
    response_model_by_alias=True,
)
async def update_product_quantity_atomic_preget(
    session: DatabaseDep,
    prod_id: int,
    atomic_op: AtomicUpdateOperations,
    value: Annotated[int, Query(gt=0)],
):
    """Update the quantity atomically and by a delta value for a Product.

    The thinking of this endpoint is that someone is taking out some items,
    they don't know the total leftover after their action but they know
    how many they took.

    There is no required JSON body.

    Returns:
        ProductPreUpdate: serialized Product with pre update quantity
    """
    LOG.debug("Updating product %s with %s", prod_id, atomic_op)
    async with session.begin():
        tobe_updated_prod = (
            await session.execute(
                select(Products).where(Products.product_id == prod_id).with_for_update()
            )
        ).scalar_one_or_none()

        # check for nonexistence - 404
        if tobe_updated_prod is None:
            await session.rollback()
            LOG.warning("Product %s not found", prod_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        # create the response object now, otherwise previous quantity value is lost
        response_prod = ProductPreUpdate.model_validate(tobe_updated_prod)

        oper = add if atomic_op == AtomicUpdateOperations.INCREMENT else sub

        tobe_updated_prod.quantity = oper(Products.quantity, value)
        # auto commit
    return response_prod
