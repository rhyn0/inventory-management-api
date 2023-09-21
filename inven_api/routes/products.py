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

    quantity: int


class ProductFull(ProductBase):
    """Define a Product for deserializing as response to HTTP request.

    Just adds 'id' field which is necessary for responses.
    """

    product_id: int


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


@ROUTER.get("/{prod_id}")
async def read_product_by_id(
    prod_id: int,
    session: DatabaseDep,
) -> ProductFull:
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
    return result  # type: ignore


@ROUTER.post("", response_model=ProductFull)
async def insert_new_product(
    new_prod: Annotated[ProductCreate, Body()], session: DatabaseDep
):
    """Take in data for a singular new product and add to database."""
    async with session.begin():
        return await session.scalar(
            insert(Products).values(new_prod.model_dump()).returning(Products)
        )


@ROUTER.delete(path="/{prod_id}", response_model=ProductFull)
async def remove_product(prod_id: int, session: DatabaseDep):
    """Remove product from database.

    This will return the deleted product
    if there are no Builds relying upon this part.

    If there is such a constraint still, respond with 405
    """
    try:
        async with session.begin():
            return await session.scalar(
                delete(Products)
                .where(Products.product_id == prod_id)
                .returning(Products)
            )
    except sa_exc.IntegrityError:
        # TODO: add logging
        # This happens due to foreign key constraint
        # from table build_parts (BuildParts)
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail="Product is still part of an active build",
        ) from None


@ROUTER.put(path="/{prod_id}", response_model=ProductFull)
async def update_product(
    prod_id: int, updated_prod: ProductUpdate, session: DatabaseDep
):
    """Update the quantity in bulk for a product.

    The thinking of this endpoint is that someone has just counted,
    the available stock of a product and is setting the current amount.
    """
    async with session.begin():
        return await session.scalar(
            update(Products)
            .where(Products.product_id == prod_id)
            .values(quantity=updated_prod.quantity)
            .returning(Products)
        )


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
