import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from catalog_service.domain.entities import Product
from catalog_service.infrastructure.models import ProductModel
from catalog_service.infrastructure.repositories import PostgresCatalogRepository


def _product(title="Hades II", stock=5, price=19990) -> Product:
    return Product(title=title, description="Roguelike", price_clp=price, stock=stock)


async def _create(session_factory, **kw) -> Product:
    async with session_factory() as s:
        return await PostgresCatalogRepository(s).create(_product(**kw))


async def test_created_product_can_be_read_back(session_factory):
    created = await _create(session_factory)
    async with session_factory() as s:
        found = await PostgresCatalogRepository(s).get_by_id(created.id)
    assert (found.title, found.price_clp, found.stock, found.genres, found.platform) == ("Hades II", 19990, 5, [], None)


async def test_unknown_id_returns_none(session_factory):
    async with session_factory() as s:
        assert await PostgresCatalogRepository(s).get_by_id(uuid.uuid4()) is None


async def test_get_all_paginates(session_factory):
    for i in range(5):
        await _create(session_factory, title=f"Game {i}")
    async with session_factory() as s:
        repo = PostgresCatalogRepository(s)
        assert len(await repo.get_all(skip=0, limit=3)) == 3
        assert len(await repo.get_all(skip=3, limit=3)) == 2


async def test_stock_cannot_go_negative(session_factory):
    created = await _create(session_factory, stock=2)
    async with session_factory() as s:
        repo = PostgresCatalogRepository(s)
        assert await repo.update_stock(created.id, -3) is False
        assert await repo.update_stock(created.id, -2) is True
    async with session_factory() as s:
        assert (await PostgresCatalogRepository(s).get_by_id(created.id)).stock == 0


async def test_update_stock_of_unknown_product_is_false(session_factory):
    async with session_factory() as s:
        assert await PostgresCatalogRepository(s).update_stock(uuid.uuid4(), 1) is False


@pytest.mark.parametrize("price,stock", [(0, 1), (100, -1)])
async def test_database_constraints_reject_invalid_rows(session_factory, price, stock):
    async with session_factory() as s:
        s.add(ProductModel(title="Bad", description="x", price_clp=price, stock=stock))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_concurrent_reservations_never_oversell(session_factory):
    created = await _create(session_factory, stock=5)

    async def reserve_one() -> bool:
        async with session_factory() as s:
            return await PostgresCatalogRepository(s).update_stock(created.id, -1)

    results = await asyncio.gather(*(reserve_one() for _ in range(20)))
    assert results.count(True) == 5
    async with session_factory() as s:
        assert (await PostgresCatalogRepository(s).get_by_id(created.id)).stock == 0


@pytest.mark.parametrize("run", [1, 2])
async def test_db_is_clean_between_tests(session_factory, run):
    await _create(session_factory, title="Unique")
    async with session_factory() as s:
        count = (await s.execute(select(func.count()).select_from(ProductModel))).scalar_one()
    assert count == 1
