"""Spec section 9: no code path may query Qdrant without a TenantScope.

Only ``beai_rag_core/qdrant_store.py`` may import or call the Qdrant client.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {ROOT / "packages/beai_rag_core/beai_rag_core/qdrant_store.py"}
SCANNED = [ROOT / "packages", ROOT / "services", ROOT / "scripts", ROOT / "eval"]

IMPORT_RE = re.compile(r"^\s*(from\s+qdrant_client\b|import\s+qdrant_client\b)", re.M)
CALL_RE = re.compile(
    r"\.(search|query_points|query_points_groups|search_batch|recommend|discover|scroll|"
    r"count|delete|upsert|retrieve|set_payload|overwrite_payload|delete_payload|"
    r"update_vectors|delete_vectors|batch_update_points|facet)\(\s*collection_name\s*="
)


def _python_files() -> list[Path]:
    return [p for d in SCANNED if d.exists() for p in d.rglob("*.py") if ".venv" not in p.parts]


def test_scanner_finds_the_store() -> None:
    files = _python_files()
    assert set(files) >= ALLOWED
    store_src = next(iter(ALLOWED)).read_text()
    assert IMPORT_RE.search(store_src)
    assert CALL_RE.search(store_src)


def test_no_qdrant_client_outside_store() -> None:
    offenders = []
    for path in _python_files():
        if path in ALLOWED:
            continue
        src = path.read_text()
        if IMPORT_RE.search(src) or CALL_RE.search(src):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"raw Qdrant client usage outside qdrant_store.py: {offenders}"
