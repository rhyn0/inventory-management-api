"""This file stores all relevant information on the PostgreSQL tables."""
# Standard Library
from datetime import datetime
from enum import StrEnum

# External Party
from sqlalchemy import func
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BIGINT
from sqlalchemy.dialects.postgresql import TEXT
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import VARCHAR
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class ProductTypes(StrEnum):
    """Enumerate all possible Product Types."""

    PART = "part"  # e.g. nails
    MATERIAL = "material"  # e.g. lumber


# TODO: include some better __repr__
class InventoryBase(DeclarativeBase):
    """Base that all tables inherit from, links sa.MetaData together."""

    # prefer to not use public schema
    metadata = sa.MetaData(schema="inventory")


class Products(InventoryBase):
    """Model of table that contains records of Product information."""

    __tablename__ = "products"
    product_id: Mapped[int] = mapped_column(
        "id", primary_key=True
    )  # automatic SERIAL create
    name: Mapped[str] = mapped_column(TEXT)
    vendor: Mapped[str] = mapped_column(TEXT)
    product_type: Mapped[ProductTypes] = mapped_column(VARCHAR(100))
    vendor_sku: Mapped[str] = mapped_column(VARCHAR(255))
    quantity: Mapped[int] = mapped_column(BIGINT, sa.CheckConstraint("quantity >= 0"))
    modified_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )


# SQLAlchemy Tables should be plural
class Tools(InventoryBase):
    """Model of table that contains the company's available tools."""

    __tablename__ = "tools"
    __table_args__ = (sa.CheckConstraint("total_owned >= total_avail"),)

    tool_id: Mapped[int] = mapped_column("id", primary_key=True)
    name: Mapped[str] = mapped_column(TEXT)
    vendor: Mapped[str] = mapped_column(TEXT)
    total_owned: Mapped[int] = mapped_column(
        # weird to keep track of a tool we don't own
        sa.CheckConstraint("total_owned > 0"),
        default=1,
    )
    total_avail: Mapped[int] = mapped_column(
        # Postgres can't do a default of column = column
        # this would require a trigger
        # instead we sensibly say that all are checked out if not told
        sa.CheckConstraint("total_avail >= 0"),
        default=0,
    )


class Builds(InventoryBase):
    """Model of table containing all builds with their unique details."""

    __tablename__ = "builds"

    build_id: Mapped[int] = mapped_column("id", primary_key=True)
    name: Mapped[str] = mapped_column(TEXT)
    sku: Mapped[str] = mapped_column(TEXT, unique=True)


class BuildParts(InventoryBase):
    """Model of intersection between Build and Product.

    Contains the products necessary to complete a build.
    """

    __tablename__ = "build_parts"

    __table_args__ = (sa.PrimaryKeyConstraint("product_id", "build_id"),)

    product_id: Mapped[int] = mapped_column(sa.ForeignKey(Products.product_id))
    build_id: Mapped[int] = mapped_column(sa.ForeignKey(Builds.build_id))
    quantity_required: Mapped[int]


class BuildTools(InventoryBase):
    """Model of intersection between Build and Tools.

    Contains the set of tools necessary to complete a build.
    """

    __tablename__ = "build_tools"

    __table_args__ = (sa.PrimaryKeyConstraint("tool_id", "build_id"),)

    tool_id: Mapped[int] = mapped_column(sa.ForeignKey(Tools.tool_id))
    build_id: Mapped[int] = mapped_column(sa.ForeignKey(Builds.build_id))
    quantity_required: Mapped[int]
