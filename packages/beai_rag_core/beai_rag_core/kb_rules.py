"""Validation rules for knowledge-base retrieval settings (spec sections 4.1 and 8)."""

CHUNK_SIZE_MIN = 200
CHUNK_SIZE_MAX = 1000
CHUNK_SIZE_STEP = 50
CHUNK_SIZE_DEFAULT = 512
CHUNK_OVERLAP_RATIO = 0.125  # 64 tokens at the default chunk size (~12%)
TOP_K_MIN = 1
TOP_K_MAX = 10
TOP_K_DEFAULT = 4
CRAWL_DEPTH_MAX = 3
MAX_PAGES_MAX = 500


def validate_chunk_size(chunk_size: int) -> int:
    if not CHUNK_SIZE_MIN <= chunk_size <= CHUNK_SIZE_MAX:
        raise ValueError(f"chunk_size must be between {CHUNK_SIZE_MIN} and {CHUNK_SIZE_MAX}")
    # The spec's default (512) is not on the step-50 slider grid; it is accepted as the one
    # off-grid value (see docs/decisions/0004-chunk-size-default.md).
    if chunk_size % CHUNK_SIZE_STEP and chunk_size != CHUNK_SIZE_DEFAULT:
        raise ValueError(f"chunk_size must be a multiple of {CHUNK_SIZE_STEP} (or the default)")
    return chunk_size


def overlap_for(chunk_size: int) -> int:
    """Overlap recomputed whenever the chunk-size slider moves."""
    return round(validate_chunk_size(chunk_size) * CHUNK_OVERLAP_RATIO)


def validate_top_k(top_k: int) -> int:
    if not TOP_K_MIN <= top_k <= TOP_K_MAX:
        raise ValueError(f"top_k must be between {TOP_K_MIN} and {TOP_K_MAX}")
    return top_k
