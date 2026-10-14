"""Bootstrap dev infrastructure and print the Qdrant collection config.

python -m app.bootstrap            # ensure collection + payload indexes + bucket
python -m app.bootstrap --show     # also print the collection config as JSON
"""

import argparse
import asyncio
import json
import sys

from app.config import get_settings
from app.resources import Resources


async def _main(show: bool) -> int:
    resources = Resources.create(get_settings())
    try:
        created = await resources.store.ensure_collection()
        await resources.storage.ensure_bucket()
        info = await resources.store.collection_info()
        if show:
            summary = {
                "collection": resources.store.collection,
                "created_now": created,
                "status": info.status,
                "vectors": info.config.params.model_dump(
                    include={"vectors", "sparse_vectors"}, mode="json", exclude_none=True
                ),
                "hnsw": info.config.hnsw_config.model_dump(mode="json"),
                "payload_indexes": {
                    k: v.model_dump(mode="json", exclude_none=True)
                    for k, v in (info.payload_schema or {}).items()
                },
            }
            sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    finally:
        await resources.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true")
    raise SystemExit(asyncio.run(_main(parser.parse_args().show)))


if __name__ == "__main__":
    main()
