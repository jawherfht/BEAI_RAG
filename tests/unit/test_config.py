import pytest
from pydantic import ValidationError

from app.config import Settings
from beai_rag_core import kb_rules
from tests.helpers import make_settings


def test_defaults_match_spec() -> None:
    s = make_settings()
    assert s.qdrant_collection == "kb_chunks"
    assert s.embed_dim == 1024
    assert s.embed_model == "microsoft/harrier-oss-v1-0.6b"
    assert s.sparse_model == "Qdrant/bm25"
    assert s.llm_disable_thinking is True
    assert s.llm_max_tokens == 200
    assert s.llm_temperature == pytest.approx(0.2)
    assert s.answer_cache_ttl_s == 86400
    assert s.max_upload_mb == 50


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        make_settings(score_threshold=0.8, conf_mid=0.55, conf_high=0.7)


def test_hs256_forbidden_in_prod() -> None:
    with pytest.raises(ValidationError):
        make_settings(environment="prod")


def test_hs_algorithms_need_secret() -> None:
    with pytest.raises(ValidationError):
        make_settings(jwt_secret=None)


def test_algorithms_accept_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_ALGORITHMS", "RS256,ES256")
    s = Settings(_env_file=None, environment="test")
    assert s.jwt_algorithms == ["RS256", "ES256"]


@pytest.mark.parametrize(("size", "overlap"), [(200, 25), (512, 64), (550, 69), (1000, 125)])
def test_overlap_is_about_12_percent(size: int, overlap: int) -> None:
    assert kb_rules.overlap_for(size) == overlap


@pytest.mark.parametrize("bad", [150, 1050, 225, 513])
def test_chunk_size_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        kb_rules.validate_chunk_size(bad)


@pytest.mark.parametrize("bad", [0, 11])
def test_top_k_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="top_k"):
        kb_rules.validate_top_k(bad)


def test_calibrated_thresholds_file_applies_unless_env_overrides(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import json

    f = tmp_path / "thresholds.json"
    f.write_text(
        json.dumps(
            {
                "embed_model": "microsoft/harrier-oss-v1-0.6b",
                "score_threshold": 0.5,
                "conf_mid": 0.55,
                "conf_high": 0.6,
            }
        )
    )
    s = make_settings(thresholds_file=str(f))
    assert (s.score_threshold, s.conf_mid, s.conf_high) == (0.5, 0.55, 0.6)
    assert s.thresholds_source == str(f)
    explicit = make_settings(thresholds_file=str(f), conf_high=0.9)
    assert explicit.conf_high == 0.9 and explicit.score_threshold == 0.5
    other_model = make_settings(thresholds_file=str(f), embed_model="Qwen/Qwen3-Embedding-0.6B")
    assert other_model.thresholds_source == "defaults"


def test_thresholds_file_can_select_the_rerank_grounding_signal(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    f = tmp_path / "thresholds.json"
    f.write_text(
        json.dumps(
            {
                "embed_model": "microsoft/harrier-oss-v1-0.6b",
                "grounding_signal": "rerank",
                "rerank_score_threshold": 0.2,
                "rerank_conf_mid": 0.6,
                "rerank_conf_high": 0.9,
            }
        )
    )
    s = make_settings(thresholds_file=str(f), rerank_provider="local")
    assert s.grounding_signal == "rerank"
    assert (s.rerank_score_threshold, s.rerank_conf_mid, s.rerank_conf_high) == (0.2, 0.6, 0.9)
    assert (
        make_settings(thresholds_file=str(f), grounding_signal="dense").grounding_signal == "dense"
    )
    with pytest.raises(ValidationError, match="GROUNDING_SIGNAL"):
        make_settings(thresholds_file=str(f), rerank_provider="none")


def test_short_hs256_secret_rejected() -> None:
    with pytest.raises(ValidationError, match="32 bytes"):
        make_settings(jwt_secret="too-short")
