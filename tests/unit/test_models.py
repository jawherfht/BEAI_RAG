from sqlalchemy import CheckConstraint, DefaultClause, Table, UniqueConstraint

from beai_rag_core.db.models import DEFAULT_FALLBACK_MESSAGE, Base, KnowledgeBase

KB_TABLE: Table = Base.metadata.tables[KnowledgeBase.__tablename__]


def test_tables_exist() -> None:
    assert set(Base.metadata.tables) == {
        "knowledge_bases",
        "sources",
        "ingestion_jobs",
        "answers_log",
    }


def _default(column: str) -> object:
    server_default = KB_TABLE.c[column].server_default
    assert isinstance(server_default, DefaultClause)
    return server_default.arg


def test_knowledge_base_defaults() -> None:
    assert _default("chunk_size") == "512"
    assert _default("chunk_overlap") == "64"
    assert _default("top_k") == "4"
    assert _default("rag_enabled") == "true"
    assert _default("hybrid_enabled") == "true"
    assert _default("rerank_enabled") == "false"
    assert _default("kb_version") == "1"
    assert _default("fallback_message") == DEFAULT_FALLBACK_MESSAGE
    assert DEFAULT_FALLBACK_MESSAGE.startswith("I'm not sure")


def test_agent_unique_per_tenant() -> None:
    uniques = [c for c in KB_TABLE.constraints if isinstance(c, UniqueConstraint)]
    assert any({col.name for col in u.columns} == {"tenant_id", "agent_id"} for u in uniques)


def test_check_constraints_present() -> None:
    names = {str(c.name) for c in KB_TABLE.constraints if isinstance(c, CheckConstraint)}
    assert {"chunk_size_range", "chunk_overlap", "top_k_range"} <= {
        n.removeprefix("ck_knowledge_bases_") for n in names
    }
