"""Script to create the necessary tables and insert default data with."""
# Standard Library
import argparse
import asyncio

# External Party
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

# Local Modules
from inven_api.common import DbConfig
from inven_api.database import BuildProducts
from inven_api.database import Builds
from inven_api.database import InventoryBase
from inven_api.database import Products
from inven_api.database import ProductTypes
from inven_api.database import Tools
from inven_api.database import get_engine
from inven_api.database.models import BuildTools

BIRDHOUSE_PRODUCTS = {
    "dowel": Products(
        name="3/8 in. x 36 in. Pine Square Dowel",
        vendor="BuildersChoice",
        product_type=ProductTypes.MATERIAL,
        vendor_sku="#BC_PSD36",  # just acronym of name with length
        quantity=2,
    ),
    "wood": Products(
        name="2 in. x 6 in. x 16 ft Doug Fir Lumber",
        vendor="Idaho Forest Group",
        product_type=ProductTypes.MATERIAL,
        vendor_sku="#IFG_DFL2_6_16",
        quantity=1,
    ),
    "nail": Products(
        name="3 in. Brite Fluted Masonry Nail",
        vendor="PRO-FIT",
        product_type=ProductTypes.PART,
        vendor_sku="#PF_BFMN3",
        quantity=10,
    ),
}

BIRDHOUSE_BUILD = Builds(
    name="Birdhouse",
    sku="IMA_BH_S",  # inventory management api birdhouse small
)

BIRDHOUSE_TOOLS = [
    Tools(
        name="Compact Auto Lock Tape Measure 9ft",
        vendor="Milwaukee",
        total_owned=5,
        total_avail=5,
    ),
    Tools(
        name="13 Amp Corded 7-1/4 in. Circular Saw",
        vendor="Ryobi",
        total_owned=2,
        total_avail=1,
    ),
    Tools(
        name="10 oz. Hammer with 9-3/4 in. Wood Handle",
        vendor="Stanley",
        total_owned=10,  # who doesn't have a lot of hammers
    ),
]


async def create_schema(engine: AsyncEngine):
    """Ensure that desired schema exists.

    This is necessary since the `Base.metadata.create_all` doesn't create the schema.
    """
    async with engine.begin() as conn:
        await conn.execute(
            sa.schema.CreateSchema(InventoryBase.metadata.schema, if_not_exists=True)
        )


async def create_tables(engine: AsyncEngine):
    """Emit DDL to create tables in the database.

    Args:
        engine (AsyncEngine): asynchronous driver engine to Postgres
    """
    async with engine.begin() as conn:
        await conn.run_sync(InventoryBase.metadata.create_all)


async def insert_starter_data(session_maker: async_sessionmaker[AsyncSession]):
    """Emit DML to put some example data into the Database.

    Args:
        session_maker: connection maker to Postgres DB
    """
    # this creates a connection to DB for this Session
    # also emit Begin for the transaction
    async with session_maker() as session, session.begin():
        # let's insert data necessary for making a birdhouse
        # i got these names by looking through HomeDepot
        session.add_all(
            [
                *BIRDHOUSE_PRODUCTS.values(),
                *BIRDHOUSE_TOOLS,
                BIRDHOUSE_BUILD,
            ]
        )


async def insert_dependent_data(session_maker: async_sessionmaker[AsyncSession]):
    """Insert the data that has foreign key constraints against prior input data.

    Primarily inputs the BuildParts items

    Args:
        session_maker (async_sessionmaker[AsyncSession]): connection maker to Postgres
    """
    async with session_maker() as session, session.begin():
        prod_result = await session.execute(sa.select(Products.product_id))
        bom_result = await session.execute(sa.select(Builds.build_id))
        tool_result = await session.execute(sa.select(Tools.tool_id))

        bom_id = bom_result.scalar_one()

        session.add_all(
            [
                BuildProducts(
                    product_id=pid,
                    build_id=bom_id,
                    quantity_required=10,
                )
                for pid in prod_result.scalars()
            ]
            + [
                BuildTools(
                    build_did=bom_id,
                    tool_id=tid,
                    quantity_required=2,
                )
                for tid in tool_result.scalars()
            ]
        )


async def main():
    """Coroutine to setup the database on first launch."""
    engine = get_engine(
        hostname=DbConfig.INVEN_DB_ENDPOINT,
        port=DbConfig.INVEN_DB_PORT,
        username=DbConfig.INVEN_DB_PASSWD,
        password=DbConfig.INVEN_DB_PASSWD,
        dbname=DbConfig.INVEN_DB_DBNAME,
    )
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    await create_schema(engine)
    await create_tables(engine)
    await insert_starter_data(async_session)
    await insert_dependent_data(async_session)
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=True)

    asyncio.run(main())
