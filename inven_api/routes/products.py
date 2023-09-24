"""Methods and routes for interacting with Products in Inventory Management API.

The products table in SQL is defined in ../database/models.py
"""
# Standard Library
from typing import Annotated
from typing import Any

# External Party
from database import Products
from database import ProductTypes
from dependencies import DatabaseDep
from dependencies import PaginationDep
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
from sqlalchemy import update

ROUTER = APIRouter(prefix="/products", tags=["products"])


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
    quantity: int


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

    Setting 'from_attributes' will help with validation from a Products item.
    """

    model_config = ConfigDict(from_attributes=True)

    product_id: int
    vendor_sku: str


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
    """Return all Products present in database."""
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
    result = (
        await session.scalars(select(Products).where(Products.product_id == prod_id))
    ).one_or_none()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not Found"
        )
    return result


@ROUTER.post("", response_model=ProductFull)
async def insert_new_product(
    new_prod: Annotated[ProductCreate, Body()], session: DatabaseDep
):
    """Take in data for a singular new product and add to database."""
    if new_prod.quantity < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be non-negative",
        )
    async with session.begin():
        try:
            return await session.scalar(
                insert(Products).values(new_prod.model_dump()).returning(Products)
            )
        except sa_exc.IntegrityError:
            # integrity can be broken if vendor_sku is not unique
            await session.rollback()
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
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Product not Found"
                )

        except sa_exc.IntegrityError:
            session.rollback()
            # TODO: add logging
            # This happens due to foreign key constraint
            # from table build_parts (BuildParts)
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="Product is still part of an active build",
            ) from None

    return result


@ROUTER.put(path="/{prod_id}", response_model=ProductFull)
async def update_product(
    prod_id: int, updated_prod: ProductUpdate, session: DatabaseDep
):
    """Update the quantity in bulk for a product.

    The thinking of this endpoint is that someone has just counted,
    the available stock of a product and is setting the current amount.
    """
    # quantity being less than 0 is handled by pydantic
    async with session.begin():
        tobe_updated_prod = (
            await session.scalars(
                select(Products.product_id, Products.vendor_sku, Products.quantity)
                .where(Products.product_id == prod_id)
                .with_for_update()
            )
        ).one_or_none()
        if tobe_updated_prod is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not Found"
            )
        tobe_updated_prod.quantity = updated_prod.quantity
        await session.commit()
    return tobe_updated_prod


@ROUTER.put(path="/{prod_id}/quantity", response_model=ProductFull)
async def update_product_quantity_by_change(
    prod_id: int, delta_quant: Annotated[int, Body()], session: DatabaseDep
):
    """Update the quantity in bulk for a product.

    The thinking of this endpoint is that someone is taking out some items,
    they don't know the total leftover after their action but they know
    how many they took.

    The body for this request is a JSON number
    """
    async with session.begin():
        return await session.scalar(
            update(Products)
            .where(Products.product_id == prod_id)
            .values(quantity=Products.quantity + delta_quant)
            .returning(Products)
        )
