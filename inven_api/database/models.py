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
from sqlalchemy.orm import relationship
from sqlalchemy.orm.exc import DetachedInstanceError


class ProductTypes(StrEnum):
    """Enumerate all possible Product Types."""

    PART = "part"  # e.g. nails
    MATERIAL = "material"  # e.g. lumber


class InventoryBase(DeclarativeBase):
    """Base that all tables inherit from, links sa.MetaData together."""

    # prefer to not use public schema
    metadata = sa.MetaData(schema="inventory")

    def __repr__(self) -> str:
        """Override repr for better debugging."""
        return self._repr()

    def _repr(self, **kwargs) -> str:
        """Helper for __repr__.

        Args:
            **kwargs: columns to include in repr

        Return:
            str
        """
        field_strings = []
        at_least_one_attached_attribute = False
        for key, field in kwargs.items():
            try:
                field_strings.append(f"{key}={field!r}")
            except DetachedInstanceError:
                field_strings.append(f"{key}=DetachedInstanceError")
            else:
                at_least_one_attached_attribute = True
        if at_least_one_attached_attribute:
            return f"<{self.__class__.__name__}({','.join(field_strings)})>"
        return f"<{self.__class__.__name__} {id(self)}>"


class Products(InventoryBase):
    """Model of table that contains records of Product information."""

    __tablename__ = "products"
    product_id: Mapped[int] = mapped_column(
        "id", primary_key=True
    )  # automatic SERIAL create
    name: Mapped[str] = mapped_column(TEXT)
    vendor: Mapped[str] = mapped_column(TEXT)
    product_type: Mapped[ProductTypes] = mapped_column(VARCHAR(100))
    vendor_sku: Mapped[str] = mapped_column(VARCHAR(255), unique=True)
    quantity: Mapped[int] = mapped_column(BIGINT, sa.CheckConstraint("quantity >= 0"))
    modified_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now()
    )

    build_products_products: Mapped[list["BuildProducts"]] = relationship(
        back_populates="parent_product",
    )

    def __repr__(self) -> str:  # noqa: D105
        return self._repr(
            id=self.product_id, name=self.name, vendor_sku=self.vendor_sku
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

    build_tools_tools: Mapped[list["BuildTools"]] = relationship(
        back_populates="parent_tool",
    )

    def __repr__(self) -> str:  # noqa: D105
        return self._repr(
            id=self.tool_id,
            name=self.name,
            total_owned=self.total_owned,
            avail=self.total_avail,
        )


class Builds(InventoryBase):
    """Model of table containing all builds with their unique details."""

    __tablename__ = "builds"

    build_id: Mapped[int] = mapped_column("id", primary_key=True)
    name: Mapped[str] = mapped_column(TEXT)
    sku: Mapped[str] = mapped_column(TEXT, unique=True)

    build_products: Mapped[list["BuildProducts"]] = relationship(
        back_populates="parent_build_product"
    )
    build_tools: Mapped[list["BuildTools"]] = relationship(
        back_populates="parent_build_tool"
    )

    def __repr__(self) -> str:  # noqa: D105
        return self._repr(id=self.build_id, name=self.name, sku=self.sku)


class BuildProducts(InventoryBase):
    """Model of intersection between Build and Product.

    Contains the products necessary to complete a build.
    """

    __tablename__ = "build_products"

    __table_args__ = (sa.PrimaryKeyConstraint("product_id", "build_id"),)

    product_id: Mapped[int] = mapped_column(
        sa.ForeignKey(Products.product_id, ondelete="RESTRICT")
    )
    build_id: Mapped[int] = mapped_column(
        sa.ForeignKey(Builds.build_id, ondelete="CASCADE")
    )
    quantity_required: Mapped[int] = mapped_column(
        # must be greater than 0, can't build with 0 of a product
        # would just unlink the dependency then
        sa.CheckConstraint("quantity_required > 0")
    )

    parent_build_product: Mapped["Builds"] = relationship(
        back_populates="build_products",
    )
    parent_product: Mapped["Products"] = relationship(
        back_populates="build_products_products",
    )

    def __repr__(self) -> str:  # noqa: D105
        return self._repr(
            product_id=self.product_id,
            build_id=self.build_id,
            quantity_req=self.quantity_required,
        )


class BuildTools(InventoryBase):
    """Model of intersection between Build and Tools.

    Contains the set of tools necessary to complete a build.
    """

    __tablename__ = "build_tools"

    __table_args__ = (sa.PrimaryKeyConstraint("tool_id", "build_id"),)

    tool_id: Mapped[int] = mapped_column(
        sa.ForeignKey(Tools.tool_id, ondelete="RESTRICT")
    )
    build_id: Mapped[int] = mapped_column(
        sa.ForeignKey(Builds.build_id, ondelete="CASCADE")
    )
    quantity_required: Mapped[int] = mapped_column(
        sa.CheckConstraint("quantity_required > 0")
    )

    parent_build_tool: Mapped["Builds"] = relationship(
        back_populates="build_tools",
    )
    parent_tool: Mapped["Tools"] = relationship(
        back_populates="build_tools_tools",
    )

    def __repr__(self) -> str:  # noqa: D105
        return self._repr(
            id=self.tool_id, build_id=self.build_id, quantity_req=self.quantity_required
        )
