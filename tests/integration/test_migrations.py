"""Alembic migrations apply cleanly, match the models and enforce spec defaults."""

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import Infra, alembic_config


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    await engine.dispose()
    return names


async def _insert_kb(url: str, chunk_size: int | None = None) -> dict[str, object]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            cols = "tenant_id, agent_id" + (", chunk_size" if chunk_size else "")
            vals = ":t, :a" + (", :cs" if chunk_size else "")
            row = (
                (
                    await conn.execute(
                        text(
                            f"INSERT INTO knowledge_bases (id, {cols}) VALUES (gen_random_uuid(), "  # noqa: S608
                            f"{vals}) RETURNING status, rag_enabled, chunk_size, chunk_overlap, "
                            "top_k, hybrid_enabled, rerank_enabled, kb_version, fallback_message"
                        ),
                        {"t": uuid.uuid4(), "a": uuid.uuid4(), "cs": chunk_size},
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)
    finally:
        await engine.dispose()


def test_upgrade_downgrade_upgrade(migrated: Infra) -> None:
    cfg = alembic_config(migrated.database_url)
    expected = {"knowledge_bases", "sources", "ingestion_jobs", "answers_log", "alembic_version"}
    assert expected <= asyncio.run(_tables(migrated.database_url))
    command.downgrade(cfg, "base")
    assert asyncio.run(_tables(migrated.database_url)) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert expected <= asyncio.run(_tables(migrated.database_url))
    command.check(cfg)  # models and migrations agree


def test_knowledge_base_defaults(migrated: Infra) -> None:
    row = asyncio.run(_insert_kb(migrated.database_url))
    assert row == {
        "status": "empty",
        "rag_enabled": True,
        "chunk_size": 512,
        "chunk_overlap": 64,
        "top_k": 4,
        "hybrid_enabled": True,
        "rerank_enabled": False,
        "kb_version": 1,
        "fallback_message": (
            "I'm not sure about that. Would you like me to connect you with someone?"
        ),
    }


@pytest.mark.parametrize("bad", [150, 1050, 525])
def test_chunk_size_constraint(migrated: Infra, bad: int) -> None:
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_kb(migrated.database_url, chunk_size=bad))
