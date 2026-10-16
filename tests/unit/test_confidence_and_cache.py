"""Confidence buckets, grounding threshold, cache keys (spec section 13)."""

import uuid

import pytest

from app.cache.answer_cache import cache_key, normalize_question
from app.retrieval.confidence import Thresholds
from beai_rag_core.enums import Confidence
from beai_rag_core.tenancy import TenantScope

T = Thresholds(score_threshold=0.45, conf_mid=0.55, conf_high=0.70)


@pytest.mark.parametrize(
    ("score", "grounded", "bucket"),
    [
        (None, False, Confidence.LOW),
        (0.10, False, Confidence.LOW),
        (0.45, True, Confidence.LOW),
        (0.549, True, Confidence.LOW),
        (0.55, True, Confidence.MEDIUM),
        (0.699, True, Confidence.MEDIUM),
        (0.70, True, Confidence.HIGH),
        (0.99, True, Confidence.HIGH),
    ],
)
def test_buckets(score: float | None, grounded: bool, bucket: Confidence) -> None:
    assert T.is_grounded(score) is grounded
    assert T.bucket(score) is bucket


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        Thresholds(0.6, 0.5, 0.7)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("What's your return policy?", "what's your return policy"),
        ("  What's   your\treturn policy ?? ", "What's your return policy"),
        ("Quelle est votre politique de retour ?", "quelle est votre politique de retour"),
        ("ما هي سياسة الإرجاع؟", "ما هي سياسة الإرجاع"),
        ("ＲＥＴＵＲＮ policy", "return policy"),  # full-width -> NFKC
    ],
)
def test_normalization_equivalence(a: str, b: str) -> None:
    assert normalize_question(a) == normalize_question(b)


def test_cache_key_includes_tenant_agent_version_and_kind() -> None:
    t, a = uuid.uuid4(), uuid.uuid4()
    base = cache_key(TenantScope(t, a), 3, "Return policy?")
    assert base == cache_key(TenantScope(t, a), 3, "return policy")
    assert base != cache_key(TenantScope(uuid.uuid4(), a), 3, "Return policy?")  # other tenant
    assert base != cache_key(TenantScope(t, uuid.uuid4()), 3, "Return policy?")  # other agent
    assert base != cache_key(TenantScope(t, a), 4, "Return policy?")  # new kb_version
    assert base != cache_key(TenantScope(t, a), 3, "Return policy?", kind="retrieval")
    assert str(t) not in base and "return" not in base  # hashed: no PII in Redis keys
