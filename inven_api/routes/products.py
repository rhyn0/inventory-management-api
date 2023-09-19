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
from fastapi import Depends
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import select

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


class ProductCreate(BaseModel):
    """Define a Product to be parsed from an incoming HTTP request.

    Very similar to the Products in ../database/models.py.
    """

    name: str
    vendor: str
    product_type: ProductTypes
    vendor_sku: str
    quantity: int


class ProductUpdate(BaseModel):
    """Define what fields can be updated on a Product."""

    quantity: int


class ProductFull(ProductCreate):
    """Define a Product for deserializing as response to HTTP request.

    Just adds 'id' field which is necessary for responses.
    """

    product_id: int


@ROUTER.get("/", response_model=list[ProductFull])
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
    return result.all()


# TODO: fix scalars
@ROUTER.get("/{prod_id}")
async def read_product_by_id(
    prod_id: int,
    session: DatabaseDep,
    product_spec: ProductDep,
) -> ProductFull:
    """Return a Product present in database.

    Does not use pagination dependency as up to one result only.
    """
    statement = _apply_spec_statement(select(Products), specs=product_spec)
    result = await session.execute(statement)
    return result.one_or_none()  # type: ignore
